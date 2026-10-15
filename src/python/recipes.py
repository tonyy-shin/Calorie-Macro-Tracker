"""
@file recipes.py
Phase 6 - Recipes
Inputs the recipe into the recipe table,
gets the recipe per portion macros,
and also lets you input a meal in as a recipe.
@author Tony Shin <tonyshin4065@gmail.com>
"""

def create_recipe(conn, user_id: int, name: str, yield_portions: int, items) -> int:
        """
        writes user input recipe into recipe table.
        @param conn - database connection
        @param user_id - the user's id
        @param name - name of the recipe that user inputted
        @param yield_portions - user inputted portions
        @param items - a list of tuple of (food_id, food_origin, grams)
        @return the new recipe id that was made
        """
        if not name or not name.strip():
                raise ValueError("name cannot be empty")
        if not isinstance(yield_portions, int):
                raise ValueError("yield portion must be a whole number") 
        if yield_portions < 1:
                raise ValueError("portion cannot be less than 1")
        if not items:
                raise ValueError("items cannot be empty")
        for food_id, food_origin, grams in items:
                if food_origin not in ("source", "manual"):
                        raise ValueError(f"invalid food origin {food_origin!r} for food id {food_id}")
                if grams is None or grams <= 0:
                        raise ValueError(f"grams must be > 0 (food_id {food_id}, got {grams})")
