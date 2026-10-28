# ADR-003: The duration trap, and why the headline is a request volume

Status: accepted. This is the decision the rest of the repository hangs off.

## The problem

This is the one project in the portfolio whose subject matter is a duration. Cost
per inference is throughput arithmetic, throughput is time, and a published
millisecond is a fact about the machine that measured it, which makes it exactly
the kind of number the receipts rules forbid as a headline.

## Decision, in four parts

**The throughput profile is an input, not a result.** `make profile` measures this
machine once and writes `fixtures/throughput/profile.json` with the full run list;
`make verify` never re-measures. Every figure downstream is re-derived from the
committed measurement, so a reviewer on different hardware reproduces every
published number exactly, and re-measures only when they choose to ask about
their own machine.

**Capacity is best of N short trials; the decision band is best against median.**
The first harness timed a fixed item count per trial, finished in about 43 milliseconds and
looked stable. Stretching trials to a second showed the truth of a shared
machine: run to run variation of a quarter, because a long window almost always
contains a neighbour stall. System noise only ever slows a run down, so the best
of 25 short trials is the least contaminated estimate of what the model sustains,
and the honest question for a decision is the band between that estimate and a
typical run: on the capture machine, a band of 16.6% against a worst case range
of 46.2%. Both are recorded; neither is hidden inside an average.

**The published headlines are counts and ratios.** The crossover at 9.2 requests
per second is a request volume. Billing inflation of 93x on SageMaker and 9,310x
on Cloud Run are ratios of a billed quantity to a measured one. The 98.66% setup
share is a share. Rates (93,104 single row requests per second; 306,284 rows per
second at batch size 128) are counts per unit of work. No anchored figure in any
checked document is a wall clock duration, and `tools/check_durations.py` sweeps
every tracked file to hold that line.

**The decision must survive the band, and the margin must clear a floor.**
The band applied is the widest one among the measured rates the race consumed:
a deferred verdict rests on the batch rate, whose committed band on this
machine is wider than the serving band, and it is held to that wider band. Exit 0
requires both: no throughput inside the measured band changes the leader, and
the leader wins by at least the declared 1.10x margin floor. Exit 1 reports
which condition failed. Exit 2 refuses outright when the band itself exceeds the
scenario's ceiling, because no comparison survives a measurement that wide; the
default ceiling of 30 sits above this machine's band deliberately, and
`--max-band-pct` tightens it to watch the refusal.

## What this costs

Headlines that are less visceral than a latency number, and a profile that must
be re-measured per machine to speak about that machine. Both costs are paid on
purpose: the alternative is a repository whose flagship figure changes meaning
with the CI runner's load average.
