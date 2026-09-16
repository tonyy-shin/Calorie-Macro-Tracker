"""
@file logging.py
1. Searches food items from foods view
2. Logs meal to tables meal_log and meal_log_items
@author Tony Shin <tonyshin4065@gmail.com>
"""



def search_foods(conn, search_term:str, user_id: int):
        """
        Searches food from foods view
        @param conn - connection to db
        @param search_term - the food we're searching for
        @param user_id - user's id
        @return the food's id, name, brand, origin, and macros
        """
        q = """
                select id, name, brand, origin, kcal, protein_g, carbs_g, fat_g
                from foods
                where name ilike %s and (origin = 'source' or user_id = %s)
                limit 20;
        """
        with conn.cursor() as cur:
                cur.execute(q, (f"%{search_term}%", user_id))
                return cur.fetchall()



def log_ad_hoc_meal(conn, user_id: int, log_date, meal_name: str, items: list[tuple[int, str, float]]) -> int:
        """
        Log an ad hoc meals.

        @param conn - database connection
        @param user_id - who is logging the meal
        @param log_date - which day the meal was logged
        @param meal_name - user defined meal name
        @param items - list of (food_id, food_origin, grams) tuples, where food_origin is 'source' or 'manual'.
                       Fails the whole log if any item doesn't resolve for this user or is missing any macro.
                       Macro totals are computed in SQL and snapshotted into meal_log.
        @return the new meal_log id.
        """
        if not items:
                raise ValueError("items cannot be empty")
        for food_id, food_origin, g in items:
                if food_origin not in ("source", "manual"):
                        raise ValueError(f"invalid food_origin {food_origin!r} for food_id {food_id}")
                if g is None or g <= 0:
                        raise ValueError(f"grams must be > 0 (food_id {food_id}, got {g})")

        ids, origins, grams = (list(x) for x in zip(*items))
        params = {
                "user_id": user_id,
                "log_date": log_date,
                "meal_name": meal_name,
                "ids": ids,
                "origins": origins,
                "grams": grams,
        }

        find_invalid_items = """
                select i.food_id, i.food_origin
                from unnest(%(ids)s::bigint[], %(origins)s::text[], %(grams)s::double precision[])
                        as i(food_id, food_origin, grams)
                left join foods f
                        on f.id = i.food_id
                        and f.origin = i.food_origin
                        and (f.origin = 'source' or f.user_id = %(user_id)s)
                where f.id is null
                        or f.kcal is null
                        or f.protein_g is null
                        or f.carbs_g is null
                        or f.fat_g is null;
        """
        insert_header = """
                insert into meal_log (user_id, log_date, meal_name, source_type, kcal, protein_g, carbs_g, fat_g)
                select %(user_id)s, %(log_date)s, %(meal_name)s, 'ad_hoc',
                        sum(f.kcal * i.grams / 100.0),
                        sum(f.protein_g * i.grams / 100.0),
                        sum(f.carbs_g * i.grams / 100.0),
                        sum(f.fat_g * i.grams / 100.0)
                from unnest(%(ids)s::bigint[], %(origins)s::text[], %(grams)s::double precision[])
                        as i(food_id, food_origin, grams)
                join foods f
                        on f.id = i.food_id
                        and f.origin = i.food_origin
                        and (f.origin = 'source' or f.user_id = %(user_id)s)
                returning id;
        """
        insert_items = """
                insert into meal_log_items (meal_log_id, food_id, food_origin, grams)
                select %(meal_log_id)s, i.food_id, i.food_origin, i.grams
                from unnest(%(ids)s::bigint[], %(origins)s::text[], %(grams)s::double precision[])
                        as i(food_id, food_origin, grams);
        """

        with conn.transaction():
                with conn.cursor() as cur:
                        cur.execute(find_invalid_items, params)
                        bad = cur.fetchall()
                        if bad:
                                raise ValueError(f"items not found or missing macros: {bad}")

                        cur.execute(insert_header, params)
                        meal_log_id = cur.fetchone()[0]

                        params["meal_log_id"] = meal_log_id
                        cur.execute(insert_items, params)

        return meal_log_id
        
