#!/usr/bin/env python3
"""Rime 处理模块

提供 Rime 输入法引擎的按键处理功能。
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from pyrime.session import Session as RimeSession

logger = logging.getLogger(__name__)


class RimeHandler:
    """Rime 按键处理器"""

    def __init__(self):
        self.session: Optional[RimeSession] = None
        self.available = self._check_rime_available()
        self._init_lock = threading.Lock()

        if self.available:
            logger.info("Rime 处理器已创建（pyrime 可用）")
        else:
            logger.info("Rime 处理器已创建（pyrime 不可用，仅语音模式）")

    def _check_rime_available(self) -> bool:
        """检查 pyrime 是否可用"""
        try:
            import pyrime
            return True
        except ImportError:
            logger.info("pyrime 未安装，Rime 集成功能将被禁用")
            return False

    def initialize(self) -> bool:
        """初始化 Rime Session（懒加载）

        Returns:
            是否初始化成功
        """
        if self.session is not None:
            return True

        if not self.available:
            return False

        with self._init_lock:
            if self.session is not None:
                return True

            try:
                # 确保日志目录存在
                log_dir = Path.home() / ".local" / "share" / "vocotype-fcitx5" / "rime"
                log_dir.mkdir(parents=True, exist_ok=True)

                from pyrime.api import Traits, API
                from pyrime.session import Session

                # 使用 fcitx5-rime 的原生用户数据目录
                user_data_dir = Path.home() / ".local" / "share" / "fcitx5" / "rime"
                if not user_data_dir.exists():
                    user_data_dir.mkdir(parents=True, exist_ok=True)

                # 查找共享数据目录
                shared_dirs = [
                    Path("/usr/share/rime-data"),
                    Path("/usr/local/share/rime-data"),
                ]
                shared_data_dir = next((d for d in shared_dirs if d.exists()), None)
                if shared_data_dir is None:
                    logger.error("找不到 Rime 共享数据目录")
                    return False

                traits = Traits(
                    shared_data_dir=str(shared_data_dir),
                    user_data_dir=str(user_data_dir),
                    log_dir=str(log_dir),
                    distribution_name="VoCoType-Fcitx5",
                    distribution_code_name="vocotype-fcitx5",
                    distribution_version="1.0",
                    app_name="rime.vocotype.fcitx5",
                )

                api = API()
                self.session = Session(traits=traits, api=api)

                # 选择已部署的 schema（pyrime 默认加载 .default）
                schema = self.session.get_current_schema()
                if schema in (None, "", ".default"):
                    schema_list = self.session.get_schema_list()
                    if schema_list:
                        first_schema = schema_list[0].schema_id
                        logger.info("选择 schema: %s", first_schema)
                        self.session.select_schema(first_schema)

                logger.info("Rime Session 已创建，schema: %s",
                          self.session.get_current_schema())
                return True

            except Exception as exc:
                logger.error("初始化 Rime Session 失败: %s", exc)
                import traceback
                traceback.print_exc()
                return False

    def process_key(self, keyval: int, mask: int) -> dict:
        """处理按键事件

        Args:
            keyval: X11 keysym 值
            mask: Rime modifier mask (0=shift, 1=lock, 2=ctrl, 3=alt)

        Returns:
            {
                "handled": bool,           # 是否被 Rime 处理
                "commit": str,             # 提交的文本（如果有）
                "preedit": {               # 预编辑信息（如果有）
                    "text": str,
                    "cursor_pos": int
                },
                "candidates": [            # 候选词列表（如果有）
                    {"text": str, "comment": str}
                ],
                "highlighted_index": int,  # 高亮的候选词索引
                "page_size": int          # 每页候选词数
            }
        """
        logger.info("process_key: keyval=%d, mask=%d, available=%s, session=%s",
                    keyval, mask, self.available, self.session is not None)

        if not self.available:
            logger.warning("Rime not available (pyrime not installed)")
            return {"handled": False}

        if not self.initialize():
            logger.warning("Rime initialization failed")
            return {"handled": False}

        try:
            # 处理按键
            handled = self.session.process_key(keyval, mask)

            result = {"handled": handled}

            # 检查提交文本
            commit = self.session.get_commit()
            if commit and commit.text:
                result["commit"] = commit.text
                logger.info("Rime 提交文本: %s", commit.text)

            # 获取上下文
            context = self.session.get_context()
            if context:
                # 预编辑文本
                preedit_text = context.composition.preedit or ""
                if preedit_text:
                    result["preedit"] = {
                        "text": preedit_text,
                        "cursor_pos": context.composition.cursor_pos
                    }

                # 候选词
                menu = context.menu
                if menu.candidates:
                    result["candidates"] = [
                        {
                            "text": c.text,
                            "comment": c.comment or ""
                        }
                        for c in menu.candidates
                    ]
                    result["highlighted_index"] = menu.highlighted_candidate_index
                    result["page_size"] = menu.page_size

            return result

        except Exception as exc:
            logger.error("Rime 处理按键失败: %s", exc)
            import traceback
            traceback.print_exc()
            return {"handled": False}

    def reset(self):
        """重置 Rime 状态（清除组合）"""
        if self.session:
            try:
                self.session.clear_composition()
                logger.debug("Rime 状态已重置")
            except Exception as exc:
                logger.warning("重置 Rime 状态失败: %s", exc)

    def cleanup(self):
        """清理资源"""
        if self.session:
            try:
                # pyrime Session 会自动清理，无需手动释放
                self.session = None
                logger.info("Rime Handler 已清理")
            except Exception as exc:
                logger.warning("清理 Rime Handler 失败: %s", exc)
