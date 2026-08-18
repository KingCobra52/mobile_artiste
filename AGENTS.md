## Docstrings
Keep docstrings short. One line if possible, max 2-3 lines for anything non-trivial.
- State what it does, not how it does it.
- Skip restating the function name in prose ("This function will...").
- Only document params/returns if the types/names aren't already self-explanatory.
- No usage examples unless the function is genuinely non-obvious.
- Prefer a single terse sentence over a structured `Args:`/`Returns:` block unless the function has 3+ params.

Bad:
    def get_user(id):
        """
        This function takes in a user id and retrieves the corresponding
        user object from the database, handling the case where the user
        might not exist by returning None in that scenario.
        """

Good:
    def get_user(id):
        """Fetch user by id, or None if not found."""
