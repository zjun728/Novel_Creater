"""Phase 3A Planning route boundary.

The mutable Planning API was retired with the aggregate foundation.  Phase 3A
fails closed until Task 7 exposes the revisioned Draft/History/Confirm routes.
"""

from fastapi import APIRouter


router = APIRouter(tags=["planning"])
