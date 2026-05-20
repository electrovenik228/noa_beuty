from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.db import transaction
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt

from .models import Sale, SaleItem, PaymentMethod, PrintQueue
from products.models import Perfume, BottleType, CosmeticProduct
from inventory.models import PerfumeStock, BottleStock, CosmeticStock
from inventory.services import apply_sale_item_to_stocks

from django.http import JsonResponse


def get_sales_stock_payload():
    perfume_stocks = {
        stock.perfume_id: stock
        for stock in PerfumeStock.objects.select_related("perfume").all()
    }
    bottle_stocks = {
        stock.bottle_type_id: stock.stock
        for stock in BottleStock.objects.all()
    }
    cosmetic_stocks = {
        stock.cosmetic_id: stock.stock
        for stock in CosmeticStock.objects.all()
    }

    perfumes = {}
    for perfume in Perfume.objects.select_related("brand").all():
        stock = perfume_stocks.get(perfume.id)
        bottles_left = stock.bottles_left if stock else 0
        ml_left = stock.ml_left if stock else 0
        perfumes[perfume.id] = {
            "price_ml": perfume.price_per_ml,
            "price_bottle": perfume.full_bottle_price,
            "bottle_ml": perfume.bottle_volume_ml,
            "name": f"{perfume.brand} {perfume.name}",
            "bottles_left": bottles_left,
            "ml_left": ml_left,
            "total_ml": bottles_left * perfume.bottle_volume_ml + ml_left,
        }

    cosmetics = {}
    for cosmetic in CosmeticProduct.objects.select_related("brand").all():
        cosmetics[cosmetic.id] = {
            "price": cosmetic.unit_price,
            "name": f"{cosmetic.brand} {cosmetic.name}",
            "stock": cosmetic_stocks.get(cosmetic.id, 0),
        }

    bottles = {}
    for bottle in BottleType.objects.all():
        bottles[bottle.id] = {
            "price": bottle.price,
            "volume_ml": bottle.volume_ml,
            "name": bottle.name,
            "is_paid": bottle.is_paid,
            "stock": bottle_stocks.get(bottle.id, 0),
            "label": (
                f"{bottle.name} {bottle.volume_ml} мл "
                f"({'%s сом' % bottle.price if bottle.is_paid else 'бесплатно'})"
            ),
        }

    return {
        "perfumes": perfumes,
        "cosmetics": cosmetics,
        "bottles": bottles,
    }


def stock_snapshot(request):
    return JsonResponse(get_sales_stock_payload())

@csrf_exempt
def enqueue_print(request, sale_id):
    PrintQueue.objects.create(
        sale_id=sale_id,
        printed=False
    )
    return JsonResponse({"status": "queued"})


# =========================
# Продажи за сегодня
# =========================
def sales_today(request):
    today = timezone.localdate()

    sales = (
        Sale.objects
        .filter(sale_date__date=today)
        .select_related("payment_method")
        .prefetch_related("items")
        .order_by("-sale_date")
    )

    # Рассчитываем общую сумму продаж за сегодня
    total_today = sum(sale.total for sale in sales)

    return render(
        request,
        "sales/sales_today.html",
        {
            "sales": sales,
            "today": today,
            "total_today": total_today,
        }
    )


def sales_today_summary(request):
    today = timezone.localdate()
    sales = Sale.objects.filter(sale_date__date=today)
    return JsonResponse({
        "count": sales.count(),
        "total": sum(sale.total for sale in sales),
        "latest_id": sales.order_by("-id").values_list("id", flat=True).first(),
    })



# =========================
# Создание продажи 
# =========================
def sale_create(request):
    perfumes = Perfume.objects.select_related("brand").all()
    bottles = BottleType.objects.all()
    cosmetics = CosmeticProduct.objects.all()
    payment_methods = PaymentMethod.objects.filter(is_active=True)

    error = None

    if request.method == "POST":
        try:
            with transaction.atomic():

                # ===== ТИП ОПЛАТЫ =====
                payment_method_id = request.POST.get("payment_method")
                if not payment_method_id:
                    raise ValueError("Не выбран тип оплаты")

                payment_method = get_object_or_404(
                    PaymentMethod, id=payment_method_id
                )

                items_data = []
                items_total = 0

                types = request.POST.getlist("item_type")
                perfumes_ids = request.POST.getlist("perfume")
                cosmetics_ids = request.POST.getlist("cosmetic")
                ml_qties = request.POST.getlist("ml_qty")
                bottle_qties = request.POST.getlist("bottle_qty")
                bottle_type_ids = request.POST.getlist("bottle_type")
                atomizer_qties = request.POST.getlist("atomizer_qty")
                prices = request.POST.getlist("price")
                item_discounts = request.POST.getlist("item_discount")

                # ===== СБОР ПОЗИЦИЙ =====
                for i, sale_type in enumerate(types):

                    perfume_id = perfumes_ids[i] or None
                    cosmetic_id = cosmetics_ids[i] or None

                    ml = float(ml_qties[i]) if ml_qties[i] else 0
                    bottles_count = int(bottle_qties[i]) if bottle_qties[i] else 0
                    bottle_type_id = bottle_type_ids[i] or None
                    atomizer_count = int(atomizer_qties[i]) if atomizer_qties[i] else 0

                    price = int(prices[i]) if prices[i] else 0
                    discount_percent = int(item_discounts[i]) if item_discounts[i] else 0
                    if not 0 <= discount_percent <= 100:
                        raise ValueError("Скидка на товар должна быть от 0 до 100%")

                    # ---- QTY ----
                    if sale_type == "split":
                        qty = ml
                    elif sale_type in ("full", "cosmetic", "gift"):
                        qty = bottles_count
                    else:
                        qty = 1

                    if sale_type == "split":
                        if not perfume_id or ml <= 0:
                            raise ValueError("Для распива выберите парфюм и количество мл")
                        perfume = get_object_or_404(Perfume, id=perfume_id)
                        stock = (
                            PerfumeStock.objects.select_for_update()
                            .filter(perfume_id=perfume_id)
                            .first()
                        )
                        total_ml = (
                            (stock.bottles_left * perfume.bottle_volume_ml) + stock.ml_left
                            if stock else 0
                        )
                        if total_ml < ml:
                            raise ValueError(f"Недостаточно остатка для распива: {perfume}")
                    elif sale_type == "full":
                        if not perfume_id or bottles_count <= 0:
                            raise ValueError("Для продажи флакона выберите парфюм и количество")
                        stock = (
                            PerfumeStock.objects.select_for_update()
                            .filter(perfume_id=perfume_id)
                            .first()
                        )
                        if not stock or stock.bottles_left < bottles_count:
                            raise ValueError("Недостаточно полных флаконов на складе")
                    elif sale_type == "cosmetic":
                        if not cosmetic_id or bottles_count <= 0:
                            raise ValueError("Для косметики выберите товар и количество")
                        stock = (
                            CosmeticStock.objects.select_for_update()
                            .filter(cosmetic_id=cosmetic_id)
                            .first()
                        )
                        if not stock or stock.stock < bottles_count:
                            raise ValueError("Недостаточно косметики на складе")
                    elif sale_type == "gift":
                        if cosmetic_id:
                            stock = (
                                CosmeticStock.objects.select_for_update()
                                .filter(cosmetic_id=cosmetic_id)
                                .first()
                            )
                            if bottles_count <= 0 or not stock or stock.stock < bottles_count:
                                raise ValueError("Недостаточно подарочной косметики на складе")
                        elif perfume_id and bottles_count > 0:
                            stock = (
                                PerfumeStock.objects.select_for_update()
                                .filter(perfume_id=perfume_id)
                                .first()
                            )
                            if not stock or stock.bottles_left < bottles_count:
                                raise ValueError("Недостаточно подарочных флаконов на складе")
                        elif perfume_id and ml > 0:
                            perfume = get_object_or_404(Perfume, id=perfume_id)
                            stock = (
                                PerfumeStock.objects.select_for_update()
                                .filter(perfume_id=perfume_id)
                                .first()
                            )
                            total_ml = (
                                (stock.bottles_left * perfume.bottle_volume_ml) + stock.ml_left
                                if stock else 0
                            )
                            if total_ml < ml:
                                raise ValueError(f"Недостаточно остатка для подарочного распива: {perfume}")
                        else:
                            raise ValueError("Для подарка выберите товар и количество")

                    if sale_type == "split" and bottle_type_id and atomizer_count > 0:
                        bottle_stock = (
                            BottleStock.objects.select_for_update()
                            .filter(bottle_type_id=bottle_type_id)
                            .first()
                        )
                        if not bottle_stock or bottle_stock.stock < atomizer_count:
                            raise ValueError("Недостаточно атомайзеров на складе")

                    # Для подарочных товаров стоимость всегда 0
                    if sale_type == "gift":
                        line_total = 0
                    else:
                        base_total = price * qty
                        discount_sum = round(base_total * discount_percent / 100)
                        line_total = max(0, base_total - discount_sum)
                        items_total += line_total

                    # ---- ПЛАТНАЯ ТАРА (только для распива, не для подарков) ----
                    if sale_type == "split" and bottle_type_id and atomizer_count > 0:
                        bottle_type = BottleType.objects.filter(id=bottle_type_id).first()
                        if bottle_type and bottle_type.is_paid:
                            items_total += bottle_type.price * atomizer_count

                    # Определяем bottle_count в зависимости от типа продажи
                    if sale_type == "split":
                        item_bottle_count = atomizer_count
                    elif sale_type == "gift":
                        # Для подарочных товаров: если распив - atomizer_count, если косметика - bottles_count, если полный флакон - 0
                        if cosmetic_id:
                            item_bottle_count = bottles_count
                        elif ml > 0:
                            item_bottle_count = atomizer_count
                        else:
                            item_bottle_count = 0
                    else:
                        item_bottle_count = bottles_count
                    
                    items_data.append({
                        "sale_type": sale_type,
                        "perfume_id": perfume_id,
                        "cosmetic_id": cosmetic_id,
                        "ml": ml,
                        "bottles_count": bottles_count,
                        "bottle_type_id": bottle_type_id,
                        "bottle_count": item_bottle_count,
                        "unit_price": price,
                        "discount_percent": discount_percent,
                        "line_total": line_total,
                    })

                # ===== СОЗДАНИЕ ЧЕКА =====
                sale_discount_percent = int(request.POST.get("sale_discount", 0))
                if not 0 <= sale_discount_percent <= 100:
                    raise ValueError("Скидка на чек должна быть от 0 до 100%")

                sale = Sale.objects.create(
                    payment_method=payment_method,
                    discount_percent=sale_discount_percent,
                    total=0,
                )

                # ===== СОЗДАНИЕ ПОЗИЦИЙ =====
                for item in items_data:
                    sale_item = SaleItem.objects.create(
                        sale=sale,
                        sale_type=item["sale_type"],
                        perfume_id=item["perfume_id"],
                        cosmetic_id=item["cosmetic_id"],
                        ml=item["ml"],
                        bottles_count=item["bottles_count"],
                        bottle_count=item["bottle_count"],
                        bottle_type_id=item["bottle_type_id"],
                        unit_price=item["unit_price"],
                        discount_percent=item["discount_percent"],
                        line_total=item["line_total"],
                    )

                    apply_sale_item_to_stocks(
                        sale_type=sale_item.sale_type,
                        perfume=sale_item.perfume,
                        cosmetic=sale_item.cosmetic,
                        bottle_type=sale_item.bottle_type,
                        bottles_count=sale_item.bottles_count,
                        ml=sale_item.ml,
                        bottle_count=sale_item.bottle_count,
                    )

                # ===== СКИДКА НА ЧЕК =====
                sale_discount_sum = round(
                    items_total * sale.discount_percent / 100
                )

                sale.total = max(0, items_total - sale_discount_sum)
                sale.save()

                # ===== В ОЧЕРЕДЬ ПЕЧАТИ =====
                PrintQueue.objects.create(sale=sale)

                messages.success(request, "Продажа успешно сохранена")
                return redirect("sales_today")

        except Exception as e:
            error = f"Ошибка при сохранении продажи: {e}"

    return render(
        request,
        "sales/sale_create.html",
        {
            "perfumes": perfumes,
            "bottles": bottles,
            "cosmetics": cosmetics,
            "payment_methods": payment_methods,
            "stock_payload": get_sales_stock_payload(),
            "error": error,
        }
    )






# =================================================
# PRINT AGENT: взять следующий чек из очереди
# =================================================
@csrf_exempt
def get_next_print(request):
    item = (
        PrintQueue.objects
        .filter(printed=False)
        .order_by("created_at")
        .first()
    )

    if not item:
        return JsonResponse({"sale_id": None})

    return JsonResponse({"sale_id": item.sale_id})


# =================================================
# PRINT AGENT: отметить чек как напечатанный
# =================================================
@csrf_exempt
def mark_printed(request, sale_id):
    PrintQueue.objects.filter(
        sale_id=sale_id,
        printed=False
    ).update(printed=True)

    return JsonResponse({"status": "ok"})

from django.http import HttpResponse
from .services.receipt_printer import render_sale_receipt_png

def receipt_png(request, sale_id):
    png = render_sale_receipt_png(sale_id)
    return HttpResponse(png, content_type="image/png")

def saleitem_list(request):
    saleitems = SaleItem.objects.select_related('sale', 'perfume', 'cosmetic', 'bottle_type').order_by('-id')
    return render(request, 'sales/saleitem_list.html', { 'saleitems': saleitems })
