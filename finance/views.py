from django.views.generic import TemplateView, CreateView, ListView, UpdateView, DeleteView
from django.utils.timezone import now
from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views import View

from sales.models import Sale, SaleItem, Expense, Income

REPORT_ACCESS_PASSWORD = "bishkek"

class MonthlyFinanceReportView(View):
    template_name = "finance/monthly_report.html"
    password_template = "finance/monthly_report_password.html"
    
    def get(self, request, *args, **kwargs):
        if request.session.get("finance_report_auth") == True:
            return self.render_report(request)
        return render(request, self.password_template, {"error": None})

    def post(self, request, *args, **kwargs):
        password = request.POST.get("password")
        if password == REPORT_ACCESS_PASSWORD:
            request.session["finance_report_auth"] = True
            return self.render_report(request)
        return render(request, self.password_template, {"error": "Неверный пароль!"})

    def render_report(self, request):
        today = now()
        month = int(request.GET.get("month", today.month))
        year = int(request.GET.get("year", today.year))

        sales = Sale.objects.filter(
            sale_date__year=year,
            sale_date__month=month
        )
        total_sales = sum(s.total for s in sales)

        extra_incomes = Income.objects.filter(
            date__year=year,
            date__month=month
        )
        total_extra_income = sum(i.amount for i in extra_incomes)

        expenses = Expense.objects.filter(
            date__year=year,
            date__month=month
        )
        total_expenses = sum(e.amount for e in expenses)

        profit = total_sales + total_extra_income - total_expenses

        context = {
            "year": year,
            "month": month,
            "sales": sales,
            "extra_incomes": extra_incomes,
            "expenses": expenses,
            "total_sales": total_sales,
            "total_extra_income": total_extra_income,
            "total_expenses": total_expenses,
            "profit": profit,
        }
        return render(request, self.template_name, context)


class ExpenseListView(ListView):
    model = Expense
    template_name = "finance/expense_list.html"
    context_object_name = "expenses"
    ordering = ["-date", "-id"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['total_amount'] = sum(expense.amount for expense in context['expenses'])
        return context

class ExpenseCreateView(CreateView):
    model = Expense
    template_name = "finance/expense_form.html"
    fields = ["description", "amount"]
    success_url = reverse_lazy("expense_list")

    def form_valid(self, form):
        messages.success(self.request, "Расход успешно добавлен")
        return super().form_valid(form)

class ExpenseUpdateView(UpdateView):
    model = Expense
    template_name = "finance/expense_form.html"
    fields = ["description", "amount"]
    success_url = reverse_lazy("expense_list")

    def form_valid(self, form):
        messages.success(self.request, "Расход успешно обновлен")
        return super().form_valid(form)

class ExpenseDeleteView(DeleteView):
    model = Expense
    template_name = "finance/expense_confirm_delete.html"
    success_url = reverse_lazy("expense_list")

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, "Расход успешно удален")
        return super().delete(request, *args, **kwargs)

class IncomeListView(ListView):
    model = Income
    template_name = "finance/income_list.html"
    context_object_name = "incomes"
    ordering = ["-date", "-id"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['total_amount'] = sum(income.amount for income in context['incomes'])
        return context

class IncomeCreateView(CreateView):
    model = Income
    template_name = "finance/income_form.html"
    fields = ["description", "amount"]
    success_url = reverse_lazy("income_list")

    def form_valid(self, form):
        messages.success(self.request, "Доход успешно добавлен")
        return super().form_valid(form)

class IncomeUpdateView(UpdateView):
    model = Income
    template_name = "finance/income_form.html"
    fields = ["description", "amount"]
    success_url = reverse_lazy("income_list")

    def form_valid(self, form):
        messages.success(self.request, "Доход успешно обновлен")
        return super().form_valid(form)

class IncomeDeleteView(DeleteView):
    model = Income
    template_name = "finance/income_confirm_delete.html"
    success_url = reverse_lazy("income_list")

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, "Доход успешно удален")
        return super().delete(request, *args, **kwargs)
