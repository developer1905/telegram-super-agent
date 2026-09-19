"""
AI vs AI & Odam vs AI Shaxmat Dvigateli (Chess Engine).
Telegram guruhlarida ikkala AI agent (SuperAgent va Arxitektor Mistral) o'rtasida
jonli, ko'rgazmali va mantiqiy shaxmat bahslarini boshqaruvchi modul.
"""

import logging
import random
from typing import Optional, Tuple

try:
    import chess
    CHESS_AVAILABLE = True
except ImportError:
    chess = None
    CHESS_AVAILABLE = False

logger = logging.getLogger(__name__)

# Shaxmat donalari uchun chiroyli emojilar
if CHESS_AVAILABLE and chess:
    PIECE_EMOJIS = {
        chess.PAWN:   {chess.WHITE: "♙", chess.BLACK: "♟"},
        chess.KNIGHT: {chess.WHITE: "♘", chess.BLACK: "♞"},
        chess.BISHOP: {chess.WHITE: "♗", chess.BLACK: "♝"},
        chess.ROOK:   {chess.WHITE: "♖", chess.BLACK: "♜"},
        chess.QUEEN:  {chess.WHITE: "♕", chess.BLACK: "♛"},
        chess.KING:   {chess.WHITE: "♔", chess.BLACK: "♚"},
    }
    PIECE_VALUES = {
        chess.PAWN: 100,
        chess.KNIGHT: 320,
        chess.BISHOP: 330,
        chess.ROOK: 500,
        chess.QUEEN: 900,
        chess.KING: 20000,
    }
else:
    PIECE_EMOJIS = {}
    PIECE_VALUES = {}


class ChessGame:
    def __init__(self, chat_id: str, white_name: str = "SuperAgent AI", black_name: str = "Arxitektor Mistral"):
        self.chat_id = str(chat_id)
        self.board = chess.Board()
        self.white_name = white_name
        self.black_name = black_name
        self.history: list[str] = []
        self.commentary_history: list[str] = []
        self.turn_count: int = 1

    def render_board(self) -> str:
        """Doskani koordinatalari bilan chiroyli emoji formatida qaytaradi."""
        lines = ["  🇦 🇧 🇨 🇩 🇪 🇫 🇬 🇭"]
        for rank in range(7, -1, -1):
            row_str = f"{rank + 1} "
            for file in range(8):
                square = chess.square(file, rank)
                piece = self.board.piece_at(square)
                if piece:
                    row_str += PIECE_EMOJIS[piece.piece_type][piece.color] + " "
                else:
                    # Shaxmat kataklari
                    row_str += "▫️ " if (rank + file) % 2 != 0 else "▪️ "
            row_str += f" {rank + 1}"
            lines.append(row_str)
        lines.append("  🇦 🇧 🇨 🇩 🇪 🇫 🇬 🇭")
        return "\n".join(lines)

    def evaluate_board(self) -> int:
        """Pozitsiyani baholash (Oqlar uchun musbat, Qoralar uchun manfiy)."""
        score = 0
        for sq, piece in self.board.piece_map().items():
            val = PIECE_VALUES[piece.piece_type]
            # Markazni nazorat qilish bonusi
            if sq in (chess.D4, chess.D5, chess.E4, chess.E5):
                val += 25
            elif sq in (chess.C3, chess.C4, chess.C5, chess.C6, chess.F3, chess.F4, chess.F5, chess.F6):
                val += 10
            score += val if piece.color == chess.WHITE else -val
        return score

    def pick_best_move(self) -> chess.Move:
        """Minimax / Alpha-Beta asosida eng yaxshi qonuniy yurishni tanlash."""
        legal_moves = list(self.board.legal_moves)
        if not legal_moves:
            return None

        is_white = self.board.turn == chess.WHITE
        best_move = random.choice(legal_moves)
        best_score = -999999 if is_white else 999999

        # Har bir yurishni tekshirish
        for move in legal_moves:
            self.board.push(move)
            score = self.evaluate_board()

            # Agar mot qilsa eng ustun
            if self.board.is_checkmate():
                score = 100000 if is_white else -100000

            self.board.pop()

            if is_white:
                if score > best_score:
                    best_score = score
                    best_move = move
            else:
                if score < best_score:
                    best_score = score
                    best_move = move

        return best_move

    def make_move(self, move: chess.Move) -> Tuple[bool, str]:
        """Yurishni amalga oshirish va san matnini qaytarish."""
        if move not in self.board.legal_moves:
            return False, "Noqonuniy yurish!"

        san = self.board.san(move)
        self.board.push(move)
        self.history.append(san)
        if self.board.turn == chess.WHITE:
            self.turn_count += 1
        return True, san

    def is_game_over(self) -> bool:
        return self.board.is_game_over()

    def get_status_summary(self) -> str:
        """O'yin holati va g'olibni aniqlash."""
        if self.board.is_checkmate():
            winner = self.black_name if self.board.turn == chess.WHITE else self.white_name
            loser = self.white_name if self.board.turn == chess.WHITE else self.black_name
            return f"🏆 **SHOH VA MOT!**\n👑 G'olib: **{winner}**\n💔 Mag'lub: **{loser}**"
        elif self.board.is_stalemate():
            return "🤝 **PAT!** O'yin durang bilan yakunlandi."
        elif self.board.is_insufficient_material():
            return "🤝 **Durang!** Doskada mot qilish uchun yetarli dona qolmadi."
        elif self.board.is_check():
            current = self.white_name if self.board.turn == chess.WHITE else self.black_name
            return f"⚠️ **SHOH!** {current} ning shohi xavf ostida!"
        return "⚔️ O'yin davom etmoqda..."


class ChessManager:
    """Barcha chatlardagi shaxmat o'yinlarini boshqaruvchi tizim."""

    def __init__(self):
        self.games: dict[str, ChessGame] = {}

    def start_game(self, chat_id: str, white_name: str = "SuperAgent AI", black_name: str = "Arxitektor Mistral") -> ChessGame:
        game = ChessGame(chat_id, white_name, black_name)
        self.games[str(chat_id)] = game
        return game

    def get_game(self, chat_id: str) -> Optional[ChessGame]:
        return self.games.get(str(chat_id))

    def stop_game(self, chat_id: str) -> bool:
        c_id = str(chat_id)
        if c_id in self.games:
            del self.games[c_id]
            return True
        return False


# Global shaxmat menejeri
chess_manager = ChessManager()
