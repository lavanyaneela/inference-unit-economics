"""inference-unit-economics: cost per inference from a rate card that cannot contain it.

A cloud rate card is denominated in instance hours and the work is denominated in
requests. The two are related only through a utilization curve the rate card cannot
contain, so no published pricing can tell you what your model costs to serve. This
package measures a local throughput profile once, treats it as a dated input with a
spread, and derives the quantity the rate card is missing: cost per thousand
inferences, per placement, per provider, and the traffic volume at which the cheap
choice changes.
"""

__version__ = "1.0.0"
