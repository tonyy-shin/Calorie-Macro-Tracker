"""
@file logging.py
1. Searches food items from foods view
2. Logs meal to tables meal_log and meal_log_items
@author Tony Shin <tonyshin4065@gmail.com>
"""




"""
Searches food from foods view
@param conn - connection to db
@param search_term - the food we're searching for
@param user_id - user's id
@return the food's id, name, brand, origin, and macros
"""
def search_foods(conn, search_term:str, user_id: int):
        q = """
                select id, name, brand, origin, kcal, protein_g, carbs_g, fat_g
                from foods
                where name ilike %s and (origin = 'source' or user_id = %s)
                limit 20;
        """
        with conn.cursor() as cur:
                cur.execute(q, (f"%{search_term}%", user_id))
                return cur.fetchall()


