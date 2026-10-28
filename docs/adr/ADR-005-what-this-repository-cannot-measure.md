# ADR-005: What this repository cannot measure

Status: accepted. The boundary, stated as its own document rather than a footnote.

## Declared, not observed

Every quantity below enters the cost model as a declared input. Each one moves
the answer, and none of them was measured here:

- The traffic (5 requests per second at the reference scenario), its peakiness,
  and the latency class that decides whether batch is in the race.
- The autoscaler's target utilization and its floor. The instance count above
  the floor is a continuous approximation that flatters autoscaling slightly;
  real autoscalers step, lag, and overshoot.
- The vCPU scaling assumption: instance capacity is the measured single process
  rate times the instance's vCPU count. This is the strongest assumption in the
  model. It ignores memory bandwidth contention, hyperthread sharing, and the
  difference between the capture machine's cores and the cloud instance's cores.
  The `vcpu_scaling_efficiency` knob exists to derate it, and E4 prices how far
  the whole profile would have to be wrong before any published decision flips.
- The serverless memory and vCPU configuration, the payload sizes, the batch
  job size, and the 120 second setup window a job is billed for.

## Not measured, and what measuring it would require

**Cold starts.** A serverless placement at low traffic serves a meaningful share
of requests from cold, which costs latency and, on some offers, billed
initialization. Measuring it needs the real services under real idle patterns:
an account, sustained wall clock time, and traffic shaping. Cold starts make the
serverless lines worse at exactly the low volumes where this model's table makes
them cheapest, so the published crossovers are a floor on the instance
placements' competitiveness, not a ceiling.

**Autoscaler lag.** Scale out that trails a burst either drops requests or
forces headroom, and headroom is money the continuous approximation does not
charge. Same requirement: live endpoints, real time.

**Network egress and cross service data paths.** The model prices the data
processing fee a provider names on the serving path; it does not price moving
the batch inputs and outputs through object storage, nor egress to callers
outside the provider.

**The cloud instances themselves.** The profile measures this machine. A cloud
vCPU of the same count is a different part, differently shared. The honest use
of this tool on a real decision is to run `make profile` on the candidate
instance type, which the design supports by treating the profile as a swappable
dated input.

## The one claim that needs an account

Whether the crossovers published here survive contact with the real services.
Everything in this repository is arithmetic over a real measured workload and
real dated prices; the step from "this is what the billing rules imply" to
"this is what the invoice says" requires deploying all 12 lines and comparing
bills, which is exactly the experiment the Pivot defers until a decision is
worth that spend.
