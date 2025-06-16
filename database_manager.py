# database_manager.py

import psycopg2
from psycopg2 import Error
from werkzeug.security import generate_password_hash 
from dotenv import load_dotenv 
import os 

# .env 파일 로드 (모듈 로드 시 가장 먼저 실행)
load_dotenv()

# --- 데이터베이스 연결 정보 (환경 변수에서 로드) ---
DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_HOST = os.getenv('DB_HOST')
DB_PORT = os.getenv('DB_PORT')

# --- 데이터베이스 연결 함수 ---
def get_db_connection():
    try:
        print(f"데이터베이스 연결 시도: host={DB_HOST}, port={DB_PORT}, dbname={DB_NAME}, user={DB_USER}, password={DB_PASSWORD}")
        conn = psycopg2.connect(
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT,
            connect_timeout=10  # 연결 타임아웃 설정
        )
        print("데이터베이스 연결 성공!")
        return conn
    except psycopg2.OperationalError as e:
        print(f"데이터베이스 연결 오류 (OperationalError): {e}")
        print(f"연결 정보: host={DB_HOST}, port={DB_PORT}, dbname={DB_NAME}, user={DB_USER}")
        return None
    except psycopg2.Error as e:
        print(f"데이터베이스 연결 오류 (Error): {e}")
        print(f"연결 정보: host={DB_HOST}, port={DB_PORT}, dbname={DB_NAME}, user={DB_USER}")
        return None
    except Exception as e:
        print(f"예상치 못한 오류 발생: {type(e).__name__}: {e}")
        return None

# --- 사용자 정보 조회 함수 ---
def get_user_by_username(username):
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None
        cursor = conn.cursor()
        sql_query = "SELECT user_id, username, password_hash, role FROM users WHERE username = %s;"
        print(f"Executing SQL: {sql_query} with params: ({username})")
        cursor.execute(sql_query, (username,))
        user = cursor.fetchone()
        return user 
    except Error as e:
        print(f"사용자 조회 오류: {e}")
        return None
    finally:
        if conn: cursor.close(); conn.close() 

# --- WMS 데이터베이스 연동 함수들 ---

def get_product_id(product_name):
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None

        cursor = conn.cursor()
        sql_query = "SELECT product_id, product_name FROM products WHERE LOWER(product_name) LIKE LOWER(%s);"
        print(f"Executing SQL: {sql_query} with params: (%{product_name}%)")
        cursor.execute(sql_query, (f'%{product_name}%',))
        result = cursor.fetchone()
        return result
    except Error as e:
        print(f"제품 ID 조회 오류: {e}")
        return None
    finally:
        if conn: cursor.close(); conn.close()

def get_location_id(location_code):
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None

        cursor = conn.cursor()
        sql_query = "SELECT location_id, location_code FROM locations WHERE LOWER(location_code) = LOWER(%s);"
        print(f"Executing SQL: {sql_query} with params: ({location_code})")
        cursor.execute(sql_query, (location_code,))
        result = cursor.fetchone()
        return result
    except Error as e:
        print(f"로케이션 ID 조회 오류: {e}")
        return None
    finally:
        if conn: cursor.close(); conn.close()

def record_inbound(product_id, quantity, location_id, supplier="AI_WMS", received_by="AI_System"):
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return False

        cursor = conn.cursor()
        
        sql_inbound = "INSERT INTO inbound (product_id, quantity, supplier, received_by) VALUES (%s, %s, %s, %s);"
        print(f"Executing SQL: {sql_inbound} with params: ({product_id}, {quantity}, {supplier}, {received_by})")
        cursor.execute(
            sql_inbound,
            (product_id, quantity, supplier, received_by)
        )
        
        sql_check_stock = "SELECT stock_id, quantity FROM stock WHERE product_id = %s AND location_id = %s;"
        print(f"Executing SQL: {sql_check_stock} with params: ({product_id}, {location_id})")
        cursor.execute(
            sql_check_stock, 
            (product_id, location_id)
        )
        existing_stock = cursor.fetchone()

        if existing_stock:
            sql_update_stock = "UPDATE stock SET quantity = quantity + %s WHERE stock_id = %s;"
            print(f"Executing SQL: {sql_update_stock} with params: ({quantity}, {existing_stock[0]})")
            cursor.execute(
                sql_update_stock,
                (quantity, existing_stock[0])
            )
            sql_update_location_weight = "UPDATE locations SET current_weight_kg = current_weight_kg + (SELECT unit_price FROM products WHERE product_id = %s) * %s WHERE location_id = %s;"
            print(f"Executing SQL: {sql_update_location_weight} with params: ({product_id}, {quantity}, {location_id})")
            cursor.execute(
                sql_update_location_weight,
                (product_id, quantity, location_id)
            )
        else:
            sql_insert_stock = "INSERT INTO stock (product_id, location_id, quantity, batch_number) VALUES (%s, %s, %s, NULL);"
            print(f"Executing SQL: {sql_insert_stock} with params: ({product_id}, {location_id}, {quantity})")
            cursor.execute(
                sql_insert_stock, 
                (product_id, location_id, quantity)
            )
            sql_update_location_weight = "UPDATE locations SET current_weight_kg = current_weight_kg + (SELECT unit_price FROM products WHERE product_id = %s) * %s WHERE location_id = %s;"
            print(f"Executing SQL: {sql_update_location_weight} with params: ({product_id}, {quantity}, {location_id})")
            cursor.execute(
                sql_update_location_weight,
                (product_id, quantity, location_id)
            )
        
        conn.commit()
        return True
    except Error as e:
        conn.rollback()
        print(f"입고 처리 오류: {e}")
        return False
    finally:
        if conn: cursor.close(); conn.close()

def record_outbound(product_id, quantity, customer="AI_WMS", shipped_by="AI_System"):
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return "DB 연결 오류"

        cursor = conn.cursor()
        sql_check_total_stock = "SELECT SUM(quantity) FROM stock WHERE product_id = %s;"
        print(f"Executing SQL: {sql_check_total_stock} with params: ({product_id})")
        cursor.execute(sql_check_total_stock, (product_id,))
        total_current_stock_result = cursor.fetchone()
        total_current_stock = total_current_stock_result[0] if total_current_stock_result and total_current_stock_result[0] is not None else 0

        if total_current_stock < quantity:
            return "재고 부족"

        sql_insert_outbound = "INSERT INTO outbound (product_id, quantity, customer, shipped_by) VALUES (%s, %s, %s, %s);"
        print(f"Executing SQL: {sql_insert_outbound} with params: ({product_id}, {quantity}, {customer}, {shipped_by})")
        cursor.execute(
            sql_insert_outbound,
            (product_id, quantity, customer, shipped_by)
        )
        
        picking_instructions = []
        remaining_to_deduct = quantity

        sql_get_available_stocks = """
            SELECT s.stock_id, s.quantity, l.location_id, l.location_code, p.product_name
            FROM stock s
            JOIN locations l ON s.location_id = l.location_id
            JOIN products p ON s.product_id = p.product_id
            WHERE s.product_id = %s AND s.quantity > 0
            ORDER BY l.location_code ASC, s.last_updated ASC;
        """
        print(f"Executing SQL: {sql_get_available_stocks.strip()} with params: ({product_id})")
        cursor.execute(sql_get_available_stocks, (product_id,))
        available_stocks = cursor.fetchall()
        
        for stock_item in available_stocks:
            stock_id, current_qty, location_db_id, location_code, product_name = stock_item 
            if remaining_to_deduct <= 0:
                break
            
            deduct_qty = min(current_qty, remaining_to_deduct)
            
            sql_update_stock = "UPDATE stock SET quantity = quantity - %s WHERE stock_id = %s;"
            print(f"Executing SQL: {sql_update_stock} with params: ({deduct_qty}, {stock_id})")
            cursor.execute(
                sql_update_stock,
                (deduct_qty, stock_id)
            )
            sql_update_location_weight = "UPDATE locations SET current_weight_kg = current_weight_kg - (SELECT unit_price FROM products WHERE product_id = %s) * %s WHERE location_id = %s;"
            print(f"Executing SQL: {sql_update_location_weight} with params: ({product_id}, {deduct_qty}, {location_db_id})")
            cursor.execute(
                sql_update_location_weight,
                (product_id, deduct_qty, location_db_id) 
            )
            
            picking_instructions.append(f"'{location_code}' 로케이션에서 '{product_name}' {deduct_qty}개를 피킹하세요.")
            remaining_to_deduct -= deduct_qty

        conn.commit()

        if remaining_to_deduct > 0:
            return "출고 처리 완료. 하지만 요청 수량만큼 재고를 찾지 못했습니다. 데이터 확인이 필요합니다."

        return {
            "status": True,
            "message": f"'{product_name}' {quantity}개를 성공적으로 출고 처리했습니다. 재고가 업데이트되었습니다.",
            "picking_instructions": picking_instructions
        }
    except Error as e:
        conn.rollback()
        print(f"출고 처리 오류: {e}")
        return f"출고 처리 중 오류가 발생했습니다: {e}"
    finally:
        if conn: cursor.close(); conn.close()

def get_current_stock(product_name=None, all_stock=False):
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None
        cursor = conn.cursor()

        if all_stock:
            sql_query = """
                SELECT p.product_name, SUM(s.quantity) as total_quantity,
                       STRING_AGG(l.location_code || ':' || s.quantity, ', ' ORDER BY l.location_code) as locations
                FROM stock s
                JOIN products p ON s.product_id = p.product_id
                LEFT JOIN locations l ON s.location_id = l.location_id
                GROUP BY p.product_name;
            """
            print(f"Executing SQL: {sql_query.strip()} for ALL STOCK (no params).")
            cursor.execute(sql_query)
        elif product_name:
            sql_query = """
                SELECT p.product_name, SUM(s.quantity) as total_quantity,
                       STRING_AGG(l.location_code || ':' || s.quantity, ', ' ORDER BY l.location_code) as locations
                FROM stock s
                JOIN products p ON s.product_id = p.product_id
                LEFT JOIN locations l ON s.location_id = l.location_id
                WHERE LOWER(p.product_name) LIKE LOWER(%s)
                GROUP BY p.product_name;
            """
            print(f"Executing SQL: {sql_query.strip()} with params: (%{product_name}%)")
            cursor.execute(sql_query, (f'%{product_name}%',))
        else:
            sql_query = """
                SELECT p.product_name, SUM(s.quantity) as total_quantity,
                       STRING_AGG(l.location_code || ':' || s.quantity, ', ' ORDER BY l.location_code) as locations
                FROM stock s
                JOIN products p ON s.product_id = p.product_id
                LEFT JOIN locations l ON s.location_id = l.location_id
                GROUP BY p.product_name;
            """
            print(f"Executing SQL: {sql_query.strip()} with no params.")
            cursor.execute(sql_query)

        results = cursor.fetchall()
        return results
    except Error as e:
        print(f"재고 조회 오류: {e}")
        return None
    finally:
        if conn: cursor.close(); conn.close()

def get_products_in_location(location_code):
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None
        cursor = conn.cursor()

        sql_query = """
            SELECT p.product_name, s.quantity
            FROM stock s
            JOIN products p ON s.product_id = p.product_id
            JOIN locations l ON s.location_id = l.location_id
            WHERE LOWER(l.location_code) = LOWER(%s);
        """
        print(f"Executing SQL: {sql_query.strip()} with params: ({location_code})")
        cursor.execute(sql_query, (location_code,))
        results = cursor.fetchall()
        return results
    except Error as e:
        print(f"로케이션별 제품 조회 오류: {e}")
        return None
    finally:
        if conn: cursor.close(); conn.close()

def get_product_id_by_id(product_id):
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None
        cursor = conn.cursor()
        sql_query = "SELECT product_id, product_name FROM products WHERE product_id = %s;"
        print(f"Executing SQL: {sql_query} with params: ({product_id})")
        cursor.execute(sql_query, (product_id,))
        result = cursor.fetchone()
        return result
    except Error as e:
        print(f"제품 ID로 제품명 조회 오류: {e}")
        return None
    finally:
        if conn: cursor.close(); conn.close()

def get_location_id_by_id(location_id): 
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None
        cursor = conn.cursor()
        sql_query = "SELECT location_id, location_code FROM locations WHERE location_id = %s;"
        print(f"Executing SQL: {sql_query} with params: ({location_id})")
        cursor.execute(sql_query, (location_id,))
        result = cursor.fetchone()
        return result
    except Error as e:
        print(f"로케이션 ID로 로케이션 코드 조회 오류: {e}")
        return None
    finally:
        if conn: cursor.close(); conn.close()

def get_all_products(): 
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None
        cursor = conn.cursor()
        sql_query = "SELECT product_id, product_name FROM products;"
        print(f"Executing SQL: {sql_query} with no params.")
        cursor.execute(sql_query)
        results = cursor.fetchall()
        return results
    except Error as e:
        print(f"모든 제품 조회 오류: {e}")
        return None
    finally:
        if conn: cursor.close(); conn.close()

def get_all_locations(): 
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None
        cursor = conn.cursor()
        sql_query = "SELECT location_id, location_code FROM locations;"
        print(f"Executing SQL: {sql_query} with no params.")
        cursor.execute(sql_query)
        results = cursor.fetchall()
        return results
    except Error as e:
        print(f"모든 로케이션 조회 오류: {e}")
        return None
    finally:
        if conn: cursor.close(); conn.close()

# --- 최신 입고 기록 조회 함수 (새로 추가) ---
def get_recent_inbounds(limit=5):
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None
        cursor = conn.cursor()
        sql_query = """
            SELECT p.product_name, i.quantity, i.inbound_date, i.supplier
            FROM inbound i
            JOIN products p ON i.product_id = p.product_id
            ORDER BY i.inbound_date DESC
            LIMIT %s;
        """
        print(f"Executing SQL: {sql_query.strip()} with params: ({limit})")
        cursor.execute(sql_query, (limit,))
        results = cursor.fetchall()
        return results
    except Error as e:
        print(f"최신 입고 기록 조회 오류: {e}")
        return None
    finally:
        if conn: cursor.close(); conn.close()

# --- 최신 출고 기록 조회 함수 (새로 추가) ---
def get_recent_outbounds(limit=5):
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None
        cursor = conn.cursor()
        sql_query = """
            SELECT p.product_name, o.quantity, o.outbound_date, o.customer
            FROM outbound o
            JOIN products p ON o.product_id = p.product_id
            ORDER BY o.outbound_date DESC
            LIMIT %s;
        """
        print(f"Executing SQL: {sql_query.strip()} with params: ({limit})")
        cursor.execute(sql_query, (limit,))
        results = cursor.fetchall()
        return results
    except Error as e:
        print(f"최신 출고 기록 조회 오류: {e}")
        return None
    finally:
        if conn: cursor.close(); conn.close()