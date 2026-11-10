# CR-01 Part A: Prediction (written before implementation)

## 1. Behaviour that will change
- `express` becomes a valid fulfillment value (spec currently allows only pickup or delivery).
- Express always costs 1,200 cents and is never waived. Pickup and standard delivery stay the same.
- The student discount is unchanged and applies to merchandise only.

## 2. Files and methods I expect to modify
- supplydesk/service.py: add an express fee constant, add "express" to FULFILLMENT_OPTIONS,
  add an express branch to the delivery calculation in _price_request(), and update the
  fulfillment error message.
- supplydesk/cli.py: add "express" to the --fulfillment choices and help text.
- supplydesk/menu.py: update the fulfillment prompt in read_request().
- README.md and FUNCTIONAL_SPEC.md: document express.
- I do not expect to change storage.py, because the saved order format is unchanged.

## 3. Tests needed
- Existing tests should still pass unchanged, apart from the same 4 known failures.
- New tests: the three CR-01 examples; express fee not waived when standard delivery
  would be free; student discount unchanged with express; quote matches placed order;
  express order survives reopening and cancellation; "shipping" and other values still
  rejected; the CLI accepts express.
