# Stock costing: weighted average

Every stock movement is valued when it is posted, and the value stays with the movement.

| Movement | Valued at | Effect on the average |
|---|---|---|
| Receipt with a price | The price after line and invoice discounts, to four decimals | Blends in: new average = (stock x average + received x price) / (stock + received) |
| Receipt without a price, return, transfer in without a cost | The current average | None |
| Issue, breakage, damage, transfer out, count loss | The current average | None |
| Transfer in | The sending location's average at that moment | Blends in at the receiving location |
| Count gain | The current average | None |
| Void of a receipt | The price that receipt was posted at | Takes that price back out of the average |

The average is held per item and per location (`inventory_balance.avg_cost`) and the cost of each movement per row (`stock_transaction.unit_cost`),
so the value of any past month is fixed and a later price change never rewrites it. An item's own `unit_cost` (shown as the starting price) is a reference price used
only until the first priced receipt; a migration set it to each item's latest priced purchase, and ticking "Update item costs" on a receipt keeps doing so.

## Cost consumed

A purchase counts on its invoice date when it has one, so a delivery invoiced on the 28th is a purchase of that month even if it was entered on the 3rd; one without an invoice date counts on the day it was entered. The ledger itself keeps the real entry time, and a void counts on the day it was made.

For a period: opening value + purchases + returns + transfers in - transfers out - closing value.
It equals issued + breakage and damage - count gains (a count loss adds to it). The Stock cost report in Reports and
`GET /api/stock/cost-report` show it per item and in total.

## Existing data

The migration replays each item and location's ledger in order. A receipt line with a price blends in at that price; every other
inward movement and the opening stock use the item's reference cost; the result is each movement's cost and each balance's average.
