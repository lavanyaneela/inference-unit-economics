# ADR-001: Rate cards as dated fixtures, not live pricing APIs

Status: accepted.

## Decision

Prices live in committed JSON fixtures under `fixtures/rate_cards/`, one per
provider, each carrying a `captured_utc` date and the source URLs the figures were
read from. Every command that prints a dollar also prints that date. The loader
refuses a card with no sources, an unknown schema, or a placement pointing at an
instance the card does not define.

## Alternative considered

Querying the providers' pricing APIs at runtime. AWS has a Price List API, Azure
has the Retail Prices API (which one of the committed sources actually is), and
GCP publishes SKU pricing through the Cloud Billing API.

Rejected for two reasons that compound. Live calls need credentials or at least
network access, which breaks the rule that `make verify` reproduces every number
offline; and prices change under you, so two people running the same command a
week apart would publish different figures from identical code, which makes every
number in the repository uncheckable in exactly the way this project exists to
avoid.

## What this costs

The prices go stale, and nothing in the repository can know when. All three cards
were captured 2026-10-28 from the published pages and the Azure Retail Prices
API; a figure quoted after a provider reprices is wrong until someone re-captures.
That is why the capture date travels with every verdict the CLI prints: a stale
answer that says when it was true is an honest answer, and a fresh looking answer
with no date is not.

## The boundary this does not move

Dated fixtures fix reproducibility, not representativeness. The cards hold on
demand list prices for one region per provider, and exclude spot, reserved and
committed use discounts on purpose (ADR-004 covers why). Nothing here claims your
negotiated rate.
