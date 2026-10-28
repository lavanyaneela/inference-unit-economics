# Defense guide: inference-unit-economics

For the author, before any conversation where this repository is on the table.
Every number here is re-measured by `make verify` and guarded by
`tools/check_numbers.py`, so this document cannot drift from the code without
failing the build.

## The thirty second version

"Cloud pricing is denominated in instance hours and my work is denominated in
requests, and the utilization curve relating them belongs to the model, not the
provider, so no pricing page can tell you what serving costs. I measured a real
model's throughput once, treated it as a dated input with an error band, and
derived cost per inference across twelve placement lines on three providers.
The result that matters: the crossover everyone plans around is mostly a
property of the provider's billing increment, not of the model, and the tool
refuses to answer when the measurement cannot support a decision."

Then stop. The question that usually comes next is "what do you mean the
crossover is a property of the provider", and the answer is the first claim
below.

## The claims, and how each is proved

**Claim: the same model flips from serverless to autoscaled at a crossover at
9.2 requests per second on GCP and a flip at 280.9 requests per second on AWS,
30.5x apart.**
Prove it: `iue crossovers --json`. The mechanism: one request finishes far
inside either billing increment (the model sustains 93,104 single row requests
per second per process), so the serverless bill is the increment, and the
increments differ 100x between the providers. If pushed: the azure entry shows
the third shape, no crossover in the swept range, because its serverless shaped
offer is billed while running (ADR-004).

**Claim: the billing increment, not the compute, is the serverless bill: 93x on
SageMaker and 9,310x on Cloud Run for this model, and on SageMaker the payload
costs 1.8 times the compute.**
Prove it: `cd experiments && PYTHONPATH=. python3 e2_cost_table.py`, read the
component columns. If pushed on "so serverless is bad": no, serverless still
wins the reference scenario (cheapest is aws/serverless at $0.11 per million,
margin of 24.13x); the claim is about what the bill is made of, which no
pricing page shows.

**Claim: the cheapest line is almost all setup: the batch bill carries a setup
share of 98.66%.**
Prove it: same E2 output, batch rows. The job itself runs at 306,284 rows per
second (batch size 128) and finishes in seconds; the 120 second billed setup
window is the bill. If pushed: the setup window is a declared input from the
rate card fixture, and ADR-005 lists it as such.

**Claim: the tool refuses rather than deciding on noise.**
Prove it: `iue decide --max-band-pct 10` exits 2, because this machine's band
is a band of 16.6% (best against median over 25 short trials; the worst case
range of 46.2% is also committed). `iue decide --providers gcp --traffic-rps
9.2` exits 1, inside the undecided zone between 8.38 and 10.14 requests per
second, a 1.21x span. If pushed on why the default ceiling is above the band:
deliberately, so the default path demonstrates a decision; the ceiling is a
scenario knob and the refusal is one flag away.

**Claim: the Terraform that provisions these placements can represent 6 of the
23 quantities the bill consumes; the other 17 have no possible home.**
Prove it: `iue coverage --json`; the mapping table is
`src/inference_unit_economics/tfgen/coverage.py`, explicit per quantity. If
pushed on "that is just your generator being thin": the 17 are structural: the
tuples are empty because no resource schema in use takes a price, a traffic
rate, a duration or a billing increment, and the two batch placements have no
resource block to put anything in.

## Questions that are meant to be hard

**Is this not just arithmetic over a pricing page?**
The arithmetic is the deliverable's smallest part. The parts a pricing page
cannot supply: the measured throughput with its band, the refusal semantics
when the band is too wide, the co-winner handling that a naive argmin gets
wrong, the undecided zones around each crossover, and the Terraform coverage
count. Arithmetic does not tell you when not to trust it.

**Your model does eleven microseconds of work. Does any of this transfer to a
real model?**
The machinery transfers unchanged: the profile is a swappable dated input, so
`make profile` on your model and your box reprices every line. The findings
scale predictably: a slower model shrinks the billing inflation and moves the
crossovers down in volume; what does not change is that the crossover's
location is set by increment, floor and utilization, which is the point. I
chose a fast model partly because it makes the rounding visible: at 100 ms
increments the effect exists for every model under 100 ms of service time.

**Your throughput came from a noisy shared machine. Why should I trust any
number downstream of it?**
Because the noise is in the deliverable. The full run list is committed, the
worst case range (it varied by 46.2%) is published next to the band, the
decision requires surviving the band, and the tool refuses when the band
exceeds the ceiling. The alternative, a clean looking number from a quiet
machine, would be less trustworthy, not more.

**What is the weakest part?**
The vCPU scaling assumption: instance capacity is the measured per process rate
times vCPU count. It ignores memory bandwidth and the difference between my
cores and cloud cores, and every instance hour line inherits it. It is named in
ADR-005, derateable via a scenario knob, and E4 prices how far it must be wrong
to flip any decision; but it is an assumption, and on a real engagement the
first thing I would do is run `make profile` on the candidate instance.

**Why no live deployment?**
Reproducibility beats realism for a portfolio artifact: every number here is
checkable by anyone with `make verify` and no credentials. The one claim that
needs an account is named in ADR-005, and the Pivot defers it until a decision
is worth the spend.

**What would you do differently with more time?**
Capture profiles on the actual cloud instance types, which the design already
accommodates; add cold start measurement behind a flag; and model request
mixes rather than a single payload size, because the data processing finding
(1.8 times the compute) suggests payload distribution moves low volume
economics more than instance choice does.

## Things to say, things not to say

Say: "the crossover is a property of the billing increment"; "the tool has
three honest answers: decided, cannot pick, and refuse"; "every figure is
re-measured by one command"; "the profile is an input with a band, not a
result".

Do not say: "serverless is always cheaper" (only below the flip, only on this
model, only at these prices); "the model costs eleven microseconds" (never
publish the duration; say 93,104 single row requests per second); "zero cost
error" (the band and the capture date are the error statement); "AWS is
cheaper than GCP" (per placement, per volume, cards captured 2026-10-28, and the
table says which).

## The live demo script

```bash
iue decide
iue decide --providers gcp --traffic-rps 9.2    # exit 1, the undecided zone
iue decide --max-band-pct 10                    # exit 2, the refusal
iue crossovers
iue coverage
```

Five commands, three exit codes, and the two headline mechanisms: the flip that
moves 30.5x apart between providers, and the 17 cannot appear count against 162
attribute paths of Terraform.
