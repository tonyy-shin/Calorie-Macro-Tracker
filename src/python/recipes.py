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

        ids, origins, gs = (list(x) for x in zip(*items))

        with conn.transaction():
                with conn.cursor() as cur:
                        cur.execute(
                                """
                                SELECT i.food_id, i.food_origin
                                FROM unnest(%s::bigint[], %s::text[]) AS i(food_id, food_origin)
                                LEFT JOIN foods f
                                        ON f.id = i.food_id
                                        AND f.origin = i.food_origin
                                        AND (f.origin = 'source' OR f.user_id = %s)
                                WHERE f.id IS NULL
                                        OR f.kcal IS NULL OR f.protein_g IS NULL
                                        OR f.carbs_g IS NULL OR f.fat_g IS NULL
                                """,
                                (ids, origins, user_id),
                        )
                        bad_items = cur.fetchall()
                        if bad_items:
                                raise ValueError(f"invalid or unusable foods: {bad_items}")

                        cur.execute(
                                """
                                INSERT INTO recipes (user_id, name, yield_portions)
                                VALUES (%s, %s, %s)
                                RETURNING id
                                """,
                                (user_id, name.strip(), yield_portions),
                        )
                        recipe_id = cur.fetchone()[0]

                        cur.execute(
                                """
                                INSERT INTO recipe_items (recipe_id, food_id, food_origin, grams)
                                SELECT %s, i.food_id, i.food_origin, i.grams
                                FROM unnest(%s::bigint[], %s::text[], %s::double precision[])
                                     AS i(food_id, food_origin, grams)
                                """,
                                (recipe_id, ids, origins, gs),
                        )
        return recipe_id



def log_recipe_meal(conn, user_id: int, log_date, recipe_id: int, portions: int, meal_name = None):
        """
        logs the recipe.
        @param conn - connection to database
        @param user_id - user's id
        @param log_date - date that the recipe was logged
        @param recipe_id - recipe_id that connects to meal_log
        @param portions - recipe portions
        @param meal_name - optional name
        @return id of new meal_log row
        """
        if isinstance(recipe_id, bool) or not isinstance(recipe_id, int):
                raise ValueError("recipe_id must be an integer")
        if isinstance(portions, bool) or not isinstance(portions, int):
                raise ValueError("portion must be a whole number")
        if portions <= 0:
                raise ValueError("portion must be greater than 0")
        if meal_name is not None:
                if not isinstance(meal_name, str) or not meal_name.strip():
                        raise ValueError("meal_name must be a non empty string")
                meal_name = meal_name.strip()

        sql = """
                insert into meal_log
                        (user_id, log_date, meal_name, source_type, recipe_id, portions, kcal, protein_g, carbs_g, fat_g)
                select
                        %(user_id)s,
                        %(log_date)s,
                        coalesce(%(meal_name)s::text, r.name),
                        'recipe',
                        r.id,
                        %(portions)s::double precision,
                        sum(f.kcal      * ri.grams / 100.0) / r.yield_portions * %(portions)s::double precision,
                        sum(f.protein_g * ri.grams / 100.0) / r.yield_portions * %(portions)s::double precision,
                        sum(f.carbs_g   * ri.grams / 100.0) / r.yield_portions * %(portions)s::double precision,
                        sum(f.fat_g     * ri.grams / 100.0) / r.yield_portions * %(portions)s::double precision
                from recipes r
                join recipe_items ri
                        on ri.recipe_id = r.id
                left join foods f
                        on f.id = ri.food_id and f.origin = ri.food_origin
                where r.id = %(recipe_id)s and r.user_id = %(user_id)s
                group by r.id, r.name, r.yield_portions
                having count(f.id) = count(*)
                        and count(*) filter (
                                where f.kcal is null or f.protein_g is null
                                or f.carbs_g is null or f.fat_g is null
                        ) = 0
                returning id
        """
        params = {
                "user_id": user_id,
                "log_date": log_date,
                "meal_name": meal_name,
                "recipe_id": recipe_id,
                "portions": portions,
        }


        with conn.transaction():
                with conn.cursor() as cur:
                        cur.execute(sql, params)
                        row = cur.fetchone()
        if row is None:
                raise ValueError("recipe not found and not owned by user")
        return row[0]
