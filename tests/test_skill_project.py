import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SkillProjectTest(unittest.TestCase):
    def run_python(self, args, env=None):
        merged_env = os.environ.copy()
        for key in list(merged_env):
            if key.startswith("XHS_IMAGE_"):
                merged_env.pop(key)
        if env:
            merged_env.update(env)
        return subprocess.run(
            [sys.executable, *args],
            cwd=ROOT,
            env=merged_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def write_prompts(self, payload):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        with tmp:
            json.dump(payload, tmp, ensure_ascii=False)
        self.addCleanup(lambda: Path(tmp.name).unlink(missing_ok=True))
        return tmp.name

    def test_validate_skill_passes(self):
        result = self.run_python(["scripts/validate_skill.py"])
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("项目校验通过", result.stdout)

    def test_skill_frontmatter_and_modes(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: xhs-notes-skill", skill)
        self.assertIn("视觉理解模式", skill)
        self.assertIn("文字规划模式", skill)
        self.assertIn("config/image_model.json", skill)
        self.assertIn("references/title_formulas.md", skill)
        self.assertIn("references/trend_keywords.md", skill)
        self.assertIn("references/meme_sentence_patterns.md", skill)
        self.assertIn("references/trend_update_rules.md", skill)
        self.assertIn("references/dynamic_clarification.md", skill)
        self.assertIn("references/topic_selection.md", skill)
        self.assertIn("references/live_formula_refresh.md", skill)
        self.assertIn("references/image_understanding_prompt.md", skill)
        self.assertIn("动态澄清规则", skill)
        self.assertIn("强制确认主题", skill)
        self.assertIn("未确认主题不得生成最终笔记", skill)
        self.assertIn("生成标题前联网搜索", skill)
        self.assertIn("request_user_input", skill)
        self.assertIn("公式联网刷新", skill)
        self.assertIn("图片理解提示词", skill)
        self.assertIn("智能选题", skill)
        self.assertIn("## 可复制发布区", skill)
        self.assertIn("## 分析说明", skill)

    def test_generate_images_reports_missing_config_without_secret(self):
        prompts_path = self.write_prompts({"prompts": ["测试封面图 prompt"]})
        result = self.run_python(["scripts/generate_images.py", "--prompts", prompts_path, "--dry-run"])
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertIn("缺少生图配置字段", payload["message"])
        self.assertNotIn("YOUR_API_KEY", result.stdout)

    def test_generate_images_dry_run_with_env(self):
        prompts_path = self.write_prompts(
            {
                "prompts": [
                    {
                        "id": "cover",
                        "prompt": "一张适合小红书的番茄鸡蛋面封面图",
                        "size": "1024x1024",
                    }
                ]
            }
        )
        result = self.run_python(
            ["scripts/generate_images.py", "--prompts", prompts_path, "--dry-run"],
            env={
                "XHS_IMAGE_BASE_URL": "https://api.example.com/v1",
                "XHS_IMAGE_MODEL": "test-image-model",
                "XHS_IMAGE_SIZE": "1024x1024",
                "XHS_IMAGE_QUALITY": "standard",
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["mode"], "dry-run")
        self.assertEqual(payload["endpoint"], "https://api.example.com/v1/images/generations")
        self.assertEqual(payload["requests"][0]["model"], "test-image-model")
        self.assertEqual(payload["requests"][0]["prompt"], "一张适合小红书的番茄鸡蛋面封面图")

    def test_readme_usage_cases(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("## 一分钟上手", readme)
        self.assertIn("## 首次执行会先确认什么", readme)
        self.assertIn("## 选择输入模式", readme)
        self.assertIn("## 联网刷新如何工作", readme)
        self.assertIn("## 图片分析会看哪些信息", readme)
        self.assertIn("## 怎样提需求效果更好", readme)
        self.assertIn("## 输出格式", readme)
        self.assertIn("## 使用案例", readme)
        self.assertIn("## 可复制发布区", readme)
        self.assertIn("视觉理解模式", readme)
        self.assertIn("文字规划模式", readme)
        self.assertIn("推荐输入结构", readme)
        self.assertIn("动态澄清", readme)
        self.assertIn("主题确认", readme)
        self.assertIn("自定义主题入口", readme)
        self.assertIn("主题强相关", readme)
        self.assertIn("选项框", readme)
        for needle in (
            "风景图生成治愈文案",
            "AI 插画生成热梗风笔记",
            "只有主题，规划完整图文笔记",
            "直接生成图片",
            "发布前风险检查和改写",
        ):
            self.assertIn(needle, readme)

    def test_required_reference_content(self):
        checks = {
            "references/title_formulas.md": ["搜索关键词型", "节点借势型", "探店本地型", "AI/创意型", "健康运动型"],
            "references/content_templates.md": ["探店推荐模板", "热点借势模板", "图片解读模板", "AI 创作拆解模板"],
            "references/tags_strategy.md": ["标签公式", "节点借势公式", "本地探店公式", "AI 创作公式", "标签自检"],
            "references/hooks_library.md": ["置顶评论模板", "避免使用"],
            "references/trend_keywords.md": ["2026 小红书趋势向热词", "长期可用的轻热词", "风险边界"],
            "references/meme_sentence_patterns.md": ["标题句式", "开头句式", "赛道适配"],
            "references/trend_update_rules.md": ["何时需要更新", "推荐校验流程", "降级策略"],
            "references/dynamic_clarification.md": [
                "强制确认主题",
                "图片主题确认",
                "文字主题确认",
                "自定义主题入口",
                "内容方向",
                "字数范围",
                "内容风格",
                "客户端原生",
                "动态生成问题",
                "联网辅助提问",
                "不要声称已弹出选项框",
            ],
            "references/topic_selection.md": ["主题确认", "选题建议", "自定义输入主题", "未确认主题不得生成最终笔记"],
            "references/live_formula_refresh.md": ["联网不可用", "回退到内置公式库", "搜索查询", "已确认主题", "实时新闻", "热梗", "主题强相关"],
            "references/image_understanding_prompt.md": ["当前农历日期", "可见事实", "合理推断", "不确定信息", "社会热点"],
            "references/risk_checklist.md": ["AI 生成内容", "发布前检查清单"],
        }
        for relative_path, needles in checks.items():
            text = (ROOT / relative_path).read_text(encoding="utf-8")
            for needle in needles:
                self.assertIn(needle, text, f"{relative_path} 缺少 {needle}")


if __name__ == "__main__":
    unittest.main()
