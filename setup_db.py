# setup_db.py

import psycopg2
from psycopg2 import Error
from werkzeug.security import generate_password_hash 
from dotenv import load_dotenv # python-dotenv 임포트 추가
import os # 환경 변수를 읽기 위해 os 모듈 임포트

# .env 파일 로드 (스크립트 실행 시 가장 먼저 실행되어 환경 변수를 설정)
load_dotenv()

# --- 데이터베이스 연결 정보 (환경 변수에서 로드) ---
DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_HOST = os.getenv('DB_HOST')
DB_PORT = os.getenv('DB_PORT')

def create_tables_and_insert_data():
    conn = None
    try:
        # 데이터베이스 연결
        conn = psycopg2.connect(
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        conn.autocommit = True 
        cursor = conn.cursor()

        print("데이터베이스에 연결되었습니다.")

        # --- 테이블 생성 ---
        # 1. Products (제품 정보)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                product_id SERIAL PRIMARY KEY,
                product_name VARCHAR(255) NOT NULL,
                sku VARCHAR(100) UNIQUE NOT NULL,
                description TEXT,
                unit_price DECIMAL(10, 2)
            );
        """)
        print("테이블 'products' 생성 완료 또는 이미 존재합니다.")

        # 2. Locations (창고 내 로케이션 정보)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS locations (
                location_id SERIAL PRIMARY KEY,
                location_code VARCHAR(50) UNIQUE NOT NULL,
                zone VARCHAR(50),
                aisle VARCHAR(50),
                shelf VARCHAR(50),
                capacity_kg DECIMAL(10, 2),
                current_weight_kg DECIMAL(10, 2) DEFAULT 0
            );
        """)
        print("테이블 'locations' 생성 완료 또는 이미 존재합니다.")

        # 3. Stock (재고 정보)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock (
                stock_id SERIAL PRIMARY KEY,
                product_id INTEGER NOT NULL REFERENCES products(product_id),
                location_id INTEGER NOT NULL REFERENCES locations(location_id),
                quantity INTEGER NOT NULL CHECK (quantity >= 0),
                batch_number VARCHAR(100),
                expiry_date DATE,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (product_id, location_id, batch_number) 
            );
        """)
        print("테이블 'stock' 생성 완료 또는 이미 존재합니다.")

        # 4. Inbound (입고 기록)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS inbound (
                inbound_id SERIAL PRIMARY KEY,
                product_id INTEGER NOT NULL REFERENCES products(product_id),
                quantity INTEGER NOT NULL,
                inbound_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                supplier VARCHAR(255),
                received_by VARCHAR(255)
            );
        """)
        print("테이블 'inbound' 생성 완료 또는 이미 존재합니다.")

        # 5. Outbound (출고 기록)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS outbound (
                outbound_id SERIAL PRIMARY KEY,
                product_id INTEGER NOT NULL REFERENCES products(product_id),
                quantity INTEGER NOT NULL,
                outbound_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                customer VARCHAR(255),
                shipped_by VARCHAR(255)
            );
        """)
        print("테이블 'outbound' 생성 완료 또는 이미 존재합니다.")

        # 6. Users (사용자 정보)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                role VARCHAR(50) NOT NULL 
            );
        """)
        print("테이블 'users' 생성 완료 또는 이미 존재합니다.")

        # --- 샘플 데이터 삽입 (테이블이 비어있을 경우에만) ---
        cursor.execute("SELECT COUNT(*) FROM products;")
        if cursor.fetchone()[0] == 0:
            print("테이블 'products'에 샘플 데이터를 삽입합니다.")
            cursor.execute("""
                INSERT INTO products (product_name, sku, description, unit_price) VALUES
                ('노트북 컴퓨터', 'NB-PRO-001', '고성능 노트북', 1500000.00),
                ('무선 마우스', 'MS-WIRELESS-002', '인체공학적 디자인', 25000.00),
                ('USB-C 허브', 'HUB-USBC-003', '7-in-1 USB-C 허브', 35000.00),
                ('HDMI 케이블', 'CABLE-HDMI-004', '2미터 고속 HDMI 케이블', 12000.00);
            """)
        else:
            print("테이블 'products'에 이미 데이터가 존재합니다. 샘플 데이터 삽입을 건너뜝니다.")

        cursor.execute("SELECT COUNT(*) FROM locations;")
        if cursor.fetchone()[0] == 0:
            print("테이블 'locations'에 샘플 데이터를 삽입합니다.")
            cursor.execute("""
                INSERT INTO locations (location_code, zone, aisle, shelf, capacity_kg) VALUES
                ('A-01-01', 'A', '01', '01', 500.00),
                ('A-01-02', 'A', '01', '02', 300.00),
                ('B-02-01', 'B', '02', '01', 700.00),
                ('C-03-05', 'C', '03', '05', 200.00);
            """)
        else:
            print("테이블 'locations'에 이미 데이터가 존재합니다. 샘플 데이터 삽입을 건너뜝니다.")

        # 샘플 사용자 계정 추가 (users 테이블이 비어있을 경우에만)
        cursor.execute("SELECT COUNT(*) FROM users;")
        if cursor.fetchone()[0] == 0:
            print("테이블 'users'에 샘플 사용자 계정을 삽입합니다.")
            # 관리자 계정
            hashed_admin_pwd = generate_password_hash('admin123')
            cursor.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s);",
                ('wmsadmin', hashed_admin_pwd, 'admin')
            )
            # 입고 관리자 계정
            hashed_inbound_pwd = generate_password_hash('inbound123')
            cursor.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s);",
                ('inbound_user', hashed_inbound_pwd, 'inbound_manager')
            )
            # 출고 관리자 계정
            hashed_outbound_pwd = generate_password_hash('outbound123')
            cursor.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s);",
                ('outbound_user', hashed_outbound_pwd, 'outbound_manager')
            )
            # 재고 관리자 계정
            hashed_inventory_pwd = generate_password_hash('inventory123')
            cursor.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s);",
                ('inventory_user', hashed_inventory_pwd, 'inventory_manager')
            )
            # 입출고 재고 관리자 계정 (all_manager)
            hashed_all_manager_pwd = generate_password_hash('all123')
            cursor.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s);",
                ('all_manager', hashed_all_manager_pwd, 'all_manager')
            )
            print("샘플 사용자 계정 삽입 완료: wmsadmin, inbound_user, outbound_user, inventory_user, all_manager")
        else:
            print("테이블 'users'에 이미 데이터가 존재합니다. 샘플 사용자 삽입을 건너뜝니다.")

        except Error as e:
            print(f"데이터베이스 작업 중 오류 발생: {e}")
        finally:
            if conn:
                cursor.close()
                conn.close()
                print("데이터베이스 연결이 종료되었습니다.")

if __name__ == "__main__":
    create_tables_and_insert_data()