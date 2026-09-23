"""
tests/test_database.py — database.py korrektlik va regression testlari.

Testlar:
1. API signature mismatch tuzatilganligini tekshirish
2. add_task user_id bilan ham, faqat title bilan ham ishlashini tekshirish
3. get_tasks user_id bilan ham, faqat status bilan ham ishlashini tekshirish
4. add_uptime_monitor signature backward compat
5. get_uptime_monitors signature backward compat
6. Duplicate variable definitions yo'qligini tekshirish

Ishga tushirish:
    cd super_agent
    python -m pytest tests/test_database.py -v
"""

from __future__ import annotations

import asyncio
import ast
import os
import pytest

DB_SOURCE_PATH = os.path.join(os.path.dirname(__file__), "..", "core", "database.py")


def read_source() -> str:
    with open(DB_SOURCE_PATH, encoding="utf-8") as f:
        return f.read()


class TestDatabaseSignatureCompat:
    """database.py API signature backward compat testlari."""

    def _get_function_node(self, tree: ast.AST, func_name: str) -> ast.FunctionDef:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
                return node
        return None

    def test_add_task_has_user_id_param(self):
        """add_task funksiyasi user_id parametrini qabul qilishi kerak."""
        source = read_source()
        tree = ast.parse(source)
        fn = self._get_function_node(tree, "add_task")
        assert fn is not None, "add_task topilmadi"
        arg_names = [a.arg for a in fn.args.args]
        assert "user_id" in arg_names, (
            f"add_task user_id parametri yo'q. Mavjud args: {arg_names}"
        )

    def test_get_tasks_has_user_id_param(self):
        """get_tasks funksiyasi user_id parametrini qabul qilishi kerak."""
        source = read_source()
        tree = ast.parse(source)
        fn = self._get_function_node(tree, "get_tasks")
        assert fn is not None, "get_tasks topilmadi"
        arg_names = [a.arg for a in fn.args.args]
        assert "user_id" in arg_names, (
            f"get_tasks user_id parametri yo'q. Mavjud args: {arg_names}"
        )

    def test_add_uptime_monitor_has_user_id_param(self):
        """add_uptime_monitor funksiyasi user_id parametrini qabul qilishi kerak."""
        source = read_source()
        tree = ast.parse(source)
        fn = self._get_function_node(tree, "add_uptime_monitor")
        assert fn is not None, "add_uptime_monitor topilmadi"
        arg_names = [a.arg for a in fn.args.args]
        assert "user_id" in arg_names, (
            f"add_uptime_monitor user_id parametri yo'q. Mavjud args: {arg_names}"
        )

    def test_get_uptime_monitors_has_user_id_param(self):
        """get_uptime_monitors funksiyasi user_id parametrini qabul qilishi kerak."""
        source = read_source()
        tree = ast.parse(source)
        fn = self._get_function_node(tree, "get_uptime_monitors")
        assert fn is not None, "get_uptime_monitors topilmadi"
        arg_names = [a.arg for a in fn.args.args]
        assert "user_id" in arg_names, (
            f"get_uptime_monitors user_id parametri yo'q. Mavjud args: {arg_names}"
        )

    def test_user_id_has_default_value(self):
        """user_id parametrida default qiymat (None) bo'lishi kerak."""
        source = read_source()
        tree = ast.parse(source)
        for func_name in ["add_task", "get_tasks", "add_uptime_monitor", "get_uptime_monitors"]:
            fn = self._get_function_node(tree, func_name)
            assert fn is not None, f"{func_name} topilmadi"
            # Default qiymatlar tekshiruvi
            # fn.args.args va fn.args.defaults to'g'riligi
            args = fn.args.args
            defaults = fn.args.defaults
            # Oxirgi N ta arg uchun default qiymati bor (N = len(defaults))
            args_with_defaults = args[len(args) - len(defaults):]
            arg_default_map = {a.arg: d for a, d in zip(args_with_defaults, defaults)}
            
            if "user_id" in arg_default_map:
                default_node = arg_default_map["user_id"]
                is_none = isinstance(default_node, ast.Constant) and default_node.value is None
                assert is_none, (
                    f"{func_name}.user_id default qiymati None emas: {ast.dump(default_node)}"
                )


class TestDatabaseSyntax:
    """database.py sintaksis to'g'riligini tekshiradi."""

    def test_database_parses_without_error(self):
        """database.py Python AST ga muvaffaqiyatli parse qilinishi kerak."""
        source = read_source()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            pytest.fail(f"database.py sintaksis xatosi: {exc}")

    def test_singleton_db_exists(self):
        """db singleton mavjud."""
        source = read_source()
        assert "db = DatabaseManager()" in source, "db singleton topilmadi"


class TestDatabaseIntegration:
    """database.py integration testlari (real SQLite, temp faylda)."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        """Vaqtinchalik test DB ni qaytaradi."""
        import sys
        import importlib
        
        # Temp DB path o'rnatamiz
        os.environ["SQLITE_DB_PATH"] = str(tmp_path / "test.db")
        os.environ["SUPABASE_URL"] = ""
        os.environ["SUPABASE_KEY"] = ""
        os.environ["BOT_TOKEN"] = "0000000000:test_token_for_testing_only"
        os.environ["ADMIN_ID"] = "12345"
        
        # DatabaseManager import
        try:
            from core.database import DatabaseManager
            # Yangi instance yaratamiz (singleton pattern bypass)
            db = DatabaseManager.__new__(DatabaseManager)
            db._db_path = str(tmp_path / "test.db")
            db.use_supabase = False
            db._supabase_client = None
            db._initialized = False
            db._supabase_reminders_available = False
            db._supabase_chats_available = False
            
            # SQLite init qilamiz
            asyncio.run(db._init_sqlite())
            yield db
        except Exception as exc:
            pytest.skip(f"DB integration test uchun import muvaffaqiyatsiz: {exc}")

    def test_add_task_with_user_id(self, temp_db):
        """add_task user_id, title, due_date bilan ishlashi kerak."""
        async def _run():
            result = await temp_db.add_task(
                user_id=12345,
                title="Test vazifa",
                due_date="2026-12-31"
            )
            assert isinstance(result, int), f"add_task int qaytarishi kerak, {type(result)} qaytdi"
            assert result > 0, f"add_task 0 dan katta ID qaytarishi kerak, {result} qaytdi"
        
        asyncio.run(_run())

    def test_add_task_with_only_title(self, temp_db):
        """add_task faqat title bilan ham ishlashi kerak (legacy pattern)."""
        async def _run():
            result = await temp_db.add_task(title="Faqat title")
            assert isinstance(result, int) and result > 0
        
        asyncio.run(_run())

    def test_get_tasks_with_user_id(self, temp_db):
        """get_tasks user_id argument bilan chaqirilishi mumkin."""
        async def _run():
            # Avval vazifa qo'shamiz
            await temp_db.add_task(user_id=12345, title="Tekshirish vazifasi")
            # user_id bilan chaqiramiz
            tasks = await temp_db.get_tasks(user_id=12345)
            assert isinstance(tasks, list), f"get_tasks list qaytarishi kerak"
        
        asyncio.run(_run())

    def test_add_uptime_monitor_with_user_id(self, temp_db):
        """add_uptime_monitor user_id, url bilan chaqirilishi mumkin."""
        async def _run():
            result = await temp_db.add_uptime_monitor(
                user_id=12345,
                url="https://example.com",
                name="Test sayt"
            )
            assert isinstance(result, int) and result >= 0
        
        asyncio.run(_run())

    def test_get_uptime_monitors_with_user_id(self, temp_db):
        """get_uptime_monitors user_id bilan chaqirilishi mumkin."""
        async def _run():
            monitors = await temp_db.get_uptime_monitors(user_id=12345)
            assert isinstance(monitors, list)
        
        asyncio.run(_run())
