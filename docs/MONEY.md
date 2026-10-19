# Money & expenses

## Expenses: the document, the bill and the payment are different things
An expense is a **posted vendor bill** on an **operating-expense account** (the document). Paying it is a separate **payment** on a cash or
bank journal (the cash movement). The platform never assumes an expense is paid: "on credit" stays a payable until a payment is recorded,
either at creation (`pay_now`) or later (`POST /money/expenses/{id}/pay`, partial payments allowed, overpaying refused).
Nothing is ever written as a manual journal entry; everything goes through Odoo's own `account.move` / `account.payment` flows.

- **Categories** (`/money/categories`, config.manage) map a friendly label to one Odoo expense account. Only accounts of type
  `expense` are offered: cost of goods sold is a different figure and is deliberately excluded.
- **Tax**: platform expenses carry no tax (the amount is the total payable) and say so (`taxes_applied: false`).
- **Approval**: an expense above `ELBLASY_EXPENSE_APPROVAL_VALUE` (default 1000) entered by anyone other than owner/manager is stored as
  `awaiting_approval` (HTTP 202) and **nothing is booked**. Owner/manager approves/rejects; nobody approves their own request; requester
  and approver are both written on the Odoo bill line.
- Every write is tracked, idempotent (`Idempotency-Key`) and verified by re-reading the bill (state, amount, account, payment state). A lost
  response + retry yields exactly one bill and one payment (tested).

## The money screen: separate figures, each defined
- **Cash and bank balances**: posted balance of the journal's account **plus the unreconciled payments booked for that journal** (Odoo
  books payments to an "outstanding payments" account until a statement is reconciled, which would otherwise leave a shop's drawer
  looking unchanged). It is a *book* balance, not a bank statement.
- **Payables**: open posted vendor bills minus open credit notes.
- **Expenses this month**: *incurred* (bill totals) vs *paid* vs *still owed*, three different numbers; by category.
- **Net profit is not shown.** It is explicitly "not available": sales minus cash expenses would be wrong (no COGS, no accruals).
- Cash/bank movement list from the journals' lines.

## Roles
money.overview / ledger: reports.view or payments.create (owner, manager, accountant). expenses: expenses.create (owner, manager,
accountant). pay: payments.create. approve: expenses.approve (owner, manager). The cashier and the stock clerk see none of it (403).

## Not yet built
Supporting documents/attachments on expenses (only a receipt-number reference), multi-currency expenses (company currency only), recurring
expenses, customer receivables/credit sales (the receivables figure is not shown rather than guessed), bank-statement reconciliation,
payments from the POS drawer that change the register's counted cash, per-tenant approval thresholds.
