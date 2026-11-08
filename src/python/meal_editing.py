"""
@file meal_editing.py
Phase 7 - Editing logged meals
Lists a day's meals, loads one for editing, updates it, and deletes it.

Snapshot rule: a meal's macros are a snapshot taken at log time. Editing
keeps that rule:
  - ad hoc meal: new items -> snapshot recomputed from the foods, in SQL
  - recipe meal: new portions -> old snapshot scaled by new/old portions,
    so it never depends on the recipe's current (possibly edited or
    deleted) ingredients
@author Tony Shin <tonyshin4065@gmail.com>
"""

import datetime


def _check_meal_id(meal_id):
        if isinstance(meal_id, bool) or not isinstance(meal_id, int):
                raise ValueError("meal_id must be an integer")


def get_meals_for_day(conn, user_id: int, log_date):
        """
        Every meal the user logged on one day, in the order they were logged.
        @return list of dicts: id, meal_name, source_type, portions,
                kcal, protein_g, carbs_g, fat_g
        """
        q = """
                select id, meal_name, source_type, portions,
                       kcal, protein_g, carbs_g, fat_g
                from meal_log
                where user_id = %s and log_date = %s
                order by logged_at, id
        """
        cols = ("id", "meal_name", "source_type", "portions",
                "kcal", "protein_g", "carbs_g", "fat_g")
        with conn.cursor() as cur:
                cur.execute(q, (user_id, log_date))
                return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_meal(conn, user_id: int, meal_id: int):
        """
        One meal with its items, for editing.
        @return dict: id, log_date, meal_name, source_type, portions, macros,
                items (ad hoc only: food_id, food_origin, grams, name, and
                per-100 g macros; name is None if the food no longer exists)
                or None if the meal isn't the user's
        """
        with conn.cursor() as cur:
                cur.execute(
                        """
                        select id, log_date, meal_name, source_type, portions,
                               kcal, protein_g, carbs_g, fat_g
                        from meal_log
                        where id = %s and user_id = %s
                        """,
                        (meal_id, user_id),
                )
                row = cur.fetchone()
                if row is None:
                        return None
                cols = ("id", "log_date", "meal_name", "source_type", "portions",
                        "kcal", "protein_g", "carbs_g", "fat_g")
                meal = dict(zip(cols, row))

                cur.execute(
                        """
                        select mi.food_id, mi.food_origin, mi.grams,
                               f.name, f.kcal, f.protein_g, f.carbs_g, f.fat_g
                        from meal_log_items mi
                        left join foods f
                                on f.id = mi.food_id
                                and f.origin = mi.food_origin
                                and (f.origin = 'source' or f.user_id = %s)
                        where mi.meal_log_id = %s
                        order by mi.id
                        """,
                        (user_id, meal_id),
                )
                item_cols = ("food_id", "food_origin", "grams",
                             "name", "kcal", "protein_g", "carbs_g", "fat_g")
                meal["items"] = [dict(zip(item_cols, r)) for r in cur.fetchall()]
        return meal


def update_meal(conn, user_id: int, meal_id: int, log_date, meal_name,
                items=None, portions=None) -> None:
        """
        Edit a logged meal.
        @param log_date - the (possibly new) date
        @param meal_name - new name; None or blank means untitled
        @param items - ad hoc meals only: the complete new list of
                       (food_id, food_origin, grams)
        @param portions - recipe meals only: new whole number of portions
        @raises ValueError on bad input, wrong meal type, or a meal that
                isn't the user's
        """
        _check_meal_id(meal_id)
        if not isinstance(log_date, datetime.date):
                raise ValueError("log_date must be a date")
        if meal_name is not None:
                if not isinstance(meal_name, str):
                        raise ValueError("meal_name must be text")
                meal_name = meal_name.strip() or None

        with conn.transaction():
                with conn.cursor() as cur:
                        cur.execute(
                                """
                                select source_type, portions from meal_log
                                where id = %s and user_id = %s
                                for update
                                """,
                                (meal_id, user_id),
                        )
                        row = cur.fetchone()
                        if row is None:
                                raise ValueError("meal not found and not owned by user")
                        source_type, old_portions = row

                        if source_type == "recipe":
                                _update_recipe_meal(cur, meal_id, log_date, meal_name,
                                                    items, portions, old_portions)
                        else:
                                _update_ad_hoc_meal(cur, user_id, meal_id, log_date,
                                                    meal_name, items, portions)


def _update_recipe_meal(cur, meal_id, log_date, meal_name, items, portions, old_portions):
        if items is not None:
                raise ValueError("recipe meals are edited by portions, not items")
        if isinstance(portions, bool) or not isinstance(portions, int) or portions < 1:
                raise ValueError("portions must be a whole number of at least 1")

        cur.execute(
                """
                update meal_log
                set log_date  = %(log_date)s,
                    meal_name = %(meal_name)s,
                    portions  = %(new)s::double precision,
                    kcal      = kcal      * %(new)s / %(old)s,
                    protein_g = protein_g * %(new)s / %(old)s,
                    carbs_g   = carbs_g   * %(new)s / %(old)s,
                    fat_g     = fat_g     * %(new)s / %(old)s
                where id = %(meal_id)s
                """,
                {"log_date": log_date, "meal_name": meal_name, "meal_id": meal_id,
                 "new": float(portions), "old": float(old_portions)},
        )


def _update_ad_hoc_meal(cur, user_id, meal_id, log_date, meal_name, items, portions):
        if portions is not None:
                raise ValueError("ad hoc meals are edited by items, not portions")
        if not items:
                raise ValueError("items cannot be empty")
        for food_id, food_origin, g in items:
                if food_origin not in ("source", "manual"):
                        raise ValueError(f"invalid food_origin {food_origin!r} for food_id {food_id}")
                if g is None or isinstance(g, bool) or g <= 0:
                        raise ValueError(f"grams must be > 0 (food_id {food_id}, got {g})")

        ids, origins, grams = (list(x) for x in zip(*items))
        params = {"user_id": user_id, "meal_id": meal_id, "log_date": log_date,
                  "meal_name": meal_name, "ids": ids, "origins": origins, "grams": grams}

        cur.execute(
                """
                select i.food_id, i.food_origin
                from unnest(%(ids)s::bigint[], %(origins)s::text[]) as i(food_id, food_origin)
                left join foods f
                        on f.id = i.food_id
                        and f.origin = i.food_origin
                        and (f.origin = 'source' or f.user_id = %(user_id)s)
                where f.id is null
                        or f.kcal is null or f.protein_g is null
                        or f.carbs_g is null or f.fat_g is null
                """,
                params,
        )
        bad = cur.fetchall()
        if bad:
                raise ValueError(f"items not found or missing macros: {bad}")

        cur.execute(
                """
                update meal_log m
                set log_date  = %(log_date)s,
                    meal_name = %(meal_name)s,
                    kcal      = t.kcal,
                    protein_g = t.protein_g,
                    carbs_g   = t.carbs_g,
                    fat_g     = t.fat_g
                from (
                        select sum(f.kcal      * i.grams / 100.0) as kcal,
                               sum(f.protein_g * i.grams / 100.0) as protein_g,
                               sum(f.carbs_g   * i.grams / 100.0) as carbs_g,
                               sum(f.fat_g     * i.grams / 100.0) as fat_g
                        from unnest(%(ids)s::bigint[], %(origins)s::text[], %(grams)s::double precision[])
                                as i(food_id, food_origin, grams)
                        join foods f
                                on f.id = i.food_id
                                and f.origin = i.food_origin
                                and (f.origin = 'source' or f.user_id = %(user_id)s)
                ) t
                where m.id = %(meal_id)s
                """,
                params,
        )
        cur.execute("delete from meal_log_items where meal_log_id = %(meal_id)s", params)
        cur.execute(
                """
                insert into meal_log_items (meal_log_id, food_id, food_origin, grams)
                select %(meal_id)s, i.food_id, i.food_origin, i.grams
                from unnest(%(ids)s::bigint[], %(origins)s::text[], %(grams)s::double precision[])
                        as i(food_id, food_origin, grams)
                """,
                params,
        )


def delete_meal(conn, user_id: int, meal_id: int) -> None:
        """
        Delete a logged meal and its items.
        @raises ValueError if the meal isn't the user's
        """
        _check_meal_id(meal_id)
        with conn.transaction():
                with conn.cursor() as cur:
                        cur.execute(
                                "select 1 from meal_log where id = %s and user_id = %s for update",
                                (meal_id, user_id),
                        )
                        if cur.fetchone() is None:
                                raise ValueError("meal not found and not owned by user")
                        cur.execute("delete from meal_log_items where meal_log_id = %s", (meal_id,))
                        cur.execute("delete from meal_log where id = %s", (meal_id,))
