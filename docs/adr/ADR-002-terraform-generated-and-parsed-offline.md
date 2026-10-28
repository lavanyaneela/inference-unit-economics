# ADR-002: Terraform generated and parsed offline, never planned or applied

Status: accepted.

## Decision

The repository generates real HCL per provider under `terraform/`, commits it, and
parses it back with `python-hcl2` for the E5 coverage map. No `terraform` binary
is assumed and no cloud account is contacted. CI regenerates the files and fails
on any diff, the same discipline applied to every other fixture.

## Alternative considered

Running `terraform plan` against real provider APIs, or `terraform validate`
against downloaded provider schemas. Both would strengthen one claim: that the
generated blocks are accepted by the providers' current schemas, not merely
well formed HCL that matches the documented resource shapes.

Rejected because `plan` needs credentials, and even `validate` needs `terraform
init` to download providers, which breaks the offline rule for a claim that is
peripheral to the repository's subject. Charter convention nine applies: surface
the missing tool rather than working around it. If a `terraform` binary is
present, nothing stops a reader running `terraform validate` in `terraform/`
after an init; the repository just does not claim that result.

## What a real plan would add, exactly

Three things, named so nobody has to guess:

1. Schema validation against the live provider versions, catching an attribute
   that was renamed since these blocks were written.
2. The plan graph, which would let E5 distinguish "absent from the file" from
   "absent from the plan", a finer cut than parsing alone gives.
3. Apply time behaviour: quota failures, IAM errors, and the actual resource
   identifiers.

None of the three changes E5's finding. The 17 structurally unrepresentable
quantities (prices, traffic, durations, increments, job windows) have no home in
any of these resource schemas, so a successful plan would contain exactly as
little of the bill as the parsed files do. The finding
is about what the format can say, not about whether a particular file says it
correctly.

## The sharpest case

The batch placement on every provider, 3 of the 12 lines in the comparison, has
no resource block at all: a SageMaker Batch Transform job, a Vertex AI batch
prediction and an Azure ML batch job are API calls with lifetimes, not
infrastructure. The cheapest lines in E2's table are therefore invisible to the
artifact an infrastructure review reads, and that absence is counted rather
than asserted: the generator commits a manifest mapping every placement to its
resource addresses, and the coverage map verifies it against the parsed files
in both directions before publishing the count.
