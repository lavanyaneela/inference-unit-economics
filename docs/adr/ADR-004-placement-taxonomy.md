# ADR-004: The placement taxonomy, and the two things called serverless

Status: accepted.

## Decision

Four placements per provider: a dedicated real time endpoint sized for peak, the
same endpoint autoscaled at a target utilization, a serverless offer, and a batch
job. Three providers, so the table prices 12 lines. Spot and reserved pricing,
committed use discounts, and GPU instances are excluded.

## Why these four

They are the four billing shapes, not the four products. Instance hours paid
around the clock; instance hours tracking load; per request billing; and job
billing with a setup window. Every managed inference product on the three
providers reduces to one of these, so the comparison generalises past the
specific services named in the rate cards.

## The taxonomy's own finding

The name serverless refers to two different billing units, and the comparison
table says so instead of papering over it. SageMaker Serverless and Cloud Run
bill per request: a rounded duration times a memory (and on Cloud Run a vCPU)
rate, plus fees. Azure Container Instances, the natural serverless shaped home
for a custom model on Azure, bills the container group for its lifetime whether
or not a request arrives. It is serverless in provisioning and dedicated in
billing, which is why the model prices it as the smallest always on unit, why it
cannot scale to zero in the table, and why above 120.7 requests per second it
becomes the cheapest interactive line on any provider: at that point the race is
between per request rounding and a small always on box, and the box wins.

A reviewer who disagrees with calling ACI serverless is agreeing with the ADR:
the word does not name a billing unit, which is precisely the trap the taxonomy
exists to surface.

## Exclusions, with reasons

Spot and reserved pricing change the question from "what does this placement
cost" to "what does this placement cost if you can tolerate eviction or commit
for years", which are capacity planning decisions with their own inputs the
scenario does not declare. Committed use discounts are negotiated, so no
committed fixture can carry them honestly. GPU instances are excluded because
the committed model is CPU bound and pricing idle accelerators would be theatre.

## What this costs

The table cannot answer "should we buy a savings plan", and says so. The
crossovers would all move under discounted instance pricing, in the direction of
favouring instance placements; the sensitivity machinery (E4) is how a reader
prices that movement without the repository guessing their discount.
