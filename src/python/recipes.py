"""
@file recipes.py
Phase 6 - Recipes
Inputs the recipe into the recipe table, loads, edits and deletes it,
gets the recipe per portion macros,
and also lets you input a meal in as a recipe.
@author Tony Shin <tonyshin4065@gmail.com>
"""

def _validate_recipe_input(name, yield_portions, items):
        """
        Shared input checks for create_recipe and update_recipe.
        @return (ids, origins, grams) as three parallel lists
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
        return ids, origins, gs


def _check_foods(cur, ids, origins, user_id):
        """
        Every ingredient must exist, be visible to the user, and have all four
        macros. Raises ValueError listing the bad (food_id, food_origin) pairs.
        """
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


def _insert_items(cur, recipe_id, ids, origins, gs):
        cur.execute(
                """
                INSERT INTO recipe_items (recipe_id, food_id, food_origin, grams)
                SELECT %s, i.food_id, i.food_origin, i.grams
                FROM unnest(%s::bigint[], %s::text[], %s::double precision[])
                     AS i(food_id, food_origin, grams)
                """,
                (recipe_id, ids, origins, gs),
        )


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
        ids, origins, gs = _validate_recipe_input(name, yield_portions, items)

        with conn.transaction():
                with conn.cursor() as cur:
                        _check_foods(cur, ids, origins, user_id)
                        cur.execute(
                                """
                                INSERT INTO recipes (user_id, name, yield_portions)
                                VALUES (%s, %s, %s)
                                RETURNING id
                                """,
                                (user_id, name.strip(), yield_portions),
                        )
                        recipe_id = cur.fetchone()[0]
                        _insert_items(cur, recipe_id, ids, origins, gs)
        return recipe_id


def get_recipe(conn, user_id: int, recipe_id: int):
        """
        Loads one recipe and its ingredients for editing.
        LEFT JOIN so an ingredient whose food no longer exists still shows up
        (name and macros None) instead of silently disappearing.
        @param conn - database connection
        @param user_id - the user's id
        @param recipe_id - the recipe to load
        @return dict {id, name, yield_portions, items: [dict]} or None if the
                recipe doesn't exist or isn't owned by the user. Each item has
                food_id, food_origin, grams, name, kcal, protein_g, carbs_g, fat_g.
        """
        with conn.cursor() as cur:
                cur.execute(
                        "select id, name, yield_portions from recipes where id = %s and user_id = %s",
                        (recipe_id, user_id),
                )
                row = cur.fetchone()
                if row is None:
                        return None
                rid, name, yield_portions = row

                cur.execute(
                        """
                        select ri.food_id, ri.food_origin, ri.grams,
                               f.name, f.kcal, f.protein_g, f.carbs_g, f.fat_g
                        from recipe_items ri
                        left join foods f
                                on f.id = ri.food_id
                                and f.origin = ri.food_origin
                                and (f.origin = 'source' or f.user_id = %s)
                        where ri.recipe_id = %s
                        order by ri.id
                        """,
                        (user_id, recipe_id),
                )
                cols = ("food_id", "food_origin", "grams",
                        "name", "kcal", "protein_g", "carbs_g", "fat_g")
                items = [dict(zip(cols, r)) for r in cur.fetchall()]

        return {"id": rid, "name": name, "yield_portions": yield_portions, "items": items}


def update_recipe(conn, user_id: int, recipe_id: int, name: str, yield_portions: int, items) -> None:
        """
        Replaces a recipe's name, yield, and full ingredient list.
        Past meal_log rows are unaffected: they hold a macro snapshot taken
        at log time.
        @param conn - database connection
        @param user_id - the user's id
        @param recipe_id - the recipe to change
        @param name - new name
        @param yield_portions - new yield
        @param items - the complete new list of (food_id, food_origin, grams)
        @raises ValueError on bad input, or if the recipe isn't the user's
        """
        if isinstance(recipe_id, bool) or not isinstance(recipe_id, int):
                raise ValueError("recipe_id must be an integer")
        ids, origins, gs = _validate_recipe_input(name, yield_portions, items)

        with conn.transaction():
                with conn.cursor() as cur:
                        _check_foods(cur, ids, origins, user_id)
                        cur.execute(
                                """
                                update recipes
                                set name = %s, yield_portions = %s
                                where id = %s and user_id = %s
                                returning id
                                """,
                                (name.strip(), yield_portions, recipe_id, user_id),
                        )
                        if cur.fetchone() is None:
                                raise ValueError("recipe not found and not owned by user")
                        cur.execute("delete from recipe_items where recipe_id = %s", (recipe_id,))
                        _insert_items(cur, recipe_id, ids, origins, gs)


def delete_recipe(conn, user_id: int, recipe_id: int) -> None:
        """
        Deletes a recipe and its ingredients. Meals already logged from it
        stay in meal_log with their name and macro snapshot; only their
        recipe_id link is cleared (meal_log.recipe_id is a foreign key).
        @raises ValueError if the recipe isn't the user's
        """
        if isinstance(recipe_id, bool) or not isinstance(recipe_id, int):
                raise ValueError("recipe_id must be an integer")

        with conn.transaction():
                with conn.cursor() as cur:
                        cur.execute(
                                "select 1 from recipes where id = %s and user_id = %s for update",
                                (recipe_id, user_id),
                        )
                        if cur.fetchone() is None:
                                raise ValueError("recipe not found and not owned by user")
                        cur.execute(
                                "update meal_log set recipe_id = null where recipe_id = %s and user_id = %s",
                                (recipe_id, user_id),
                        )
                        cur.execute("delete from recipe_items where recipe_id = %s", (recipe_id,))
                        cur.execute("delete from recipes where id = %s", (recipe_id,))



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
