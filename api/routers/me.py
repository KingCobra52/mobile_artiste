"""The signed-in user's own account."""
from fastapi import APIRouter, Depends, HTTPException

from api.auth import AuthenticatedUser, get_current_user
from api.db import get_db
from api.models import Profile

router = APIRouter(tags=["account"])

PROFILE_QUERY = "SELECT id, username, bars FROM profiles WHERE id = %s"


@router.get("/me", response_model=Profile)
def me(user: AuthenticatedUser = Depends(get_current_user), db=Depends(get_db)):
    row = db.execute(PROFILE_QUERY, (user.id,)).fetchone()
    if row is None:
        # The trigger on auth.users creates this row at signup, so its absence
        # means the account predates the trigger or the row was deleted by hand.
        raise HTTPException(status_code=404, detail="No profile for this account")
    # email isn't a profiles column - it lives on auth.users and reaches us
    # through the verified token claims
    return dict(row, email=user.email)
