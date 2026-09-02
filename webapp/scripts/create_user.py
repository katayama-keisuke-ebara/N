"""初期ユーザーを登録するシードスクリプト (自己登録UIは提供しないため管理者が実行する)。

使い方:
    .venv\\Scripts\\python.exe -m webapp.scripts.create_user <username>
パスワードは対話プロンプトで入力する(コマンド引数に平文パスワードを渡さない)。
"""

from __future__ import annotations

import argparse
import getpass
import sys

from webapp import db, security


def main() -> int:
    parser = argparse.ArgumentParser(description="NetsingTool Web の初期ユーザーを作成する")
    parser.add_argument("username")
    args = parser.parse_args()

    db.init_db()
    if db.get_user_by_username(args.username) is not None:
        print(f"ユーザー '{args.username}' は既に存在します", file=sys.stderr)
        return 1

    password = getpass.getpass("パスワード: ")
    password_confirm = getpass.getpass("パスワード(確認): ")
    if password != password_confirm:
        print("パスワードが一致しません", file=sys.stderr)
        return 1
    if len(password) < 8:
        print("パスワードは 8 文字以上にしてください", file=sys.stderr)
        return 1

    db.create_user(args.username, security.hash_password(password))
    print(f"ユーザー '{args.username}' を作成しました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
