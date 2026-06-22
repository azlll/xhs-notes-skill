import base64
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

    def write_json(self, payload):
        return self.write_prompts(payload)

    def write_png(self):
        payload = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
        tmp = tempfile.NamedTemporaryFile("wb", suffix=".png", delete=False)
        with tmp:
            tmp.write(base64.b64decode(payload))
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
        self.assertIn("references/fallback_outputs.md", skill)
        self.assertIn("references/post_publish_review.md", skill)
        self.assertIn("scripts/generate_review_report.py", skill)
        self.assertIn("动态澄清规则", skill)
        self.assertIn("强制确认主题", skill)
        self.assertIn("未确认主题不得生成最终笔记", skill)
        self.assertIn("生成标题前联网搜索", skill)
        self.assertIn("request_user_input", skill)
        self.assertIn("公式联网刷新", skill)
        self.assertIn("图片理解提示词", skill)
        self.assertIn("智能选题", skill)
        self.assertIn("发布后复盘模式", skill)
        self.assertIn("HTML 看板", skill)
        self.assertIn("六维评分", skill)
        self.assertIn("小眼睛/观看", skill)
        self.assertIn("流量漏斗", skill)
        self.assertIn("封面标题点击诊断", skill)
        self.assertIn("目标人群与关键词匹配", skill)
        self.assertIn("脚本可用性与降级输出", skill)
        self.assertIn("ASCII 示例图", skill)
        self.assertIn("Markdown 降级版", skill)
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

    def test_generate_review_report_html(self):
        image_path = self.write_png()
        review_path = self.write_json(
            {
                "report_id": "unit-review",
                "note": {
                    "title": "工作日中午，我偷偷去咖啡厅充了个电",
                    "body": "工作日中午，突然不想把午休也过得很赶。",
                    "tags": ["工作日午休", "打工人自救", "咖啡厅日常"],
                    "published_at": "2026-06-17 12:30",
                    "goal": "提升收藏和评论",
                    "link": "https://www.xiaohongshu.com/explore/example",
                    "images": [image_path],
                },
                "metrics": {
                    "exposure": 3200,
                    "views": 680,
                    "likes": 96,
                    "favorites": 42,
                    "comments": 11,
                    "shares": 8,
                    "follows": 5,
                },
                "traffic": {
                    "conclusion": "观看后点赞强于收藏，内容更偏情绪共鸣。",
                    "funnel_issue": "更可能卡在收藏价值。",
                    "cover_title_diagnosis": "有曝光和小眼睛，可判断封面标题点击效率。",
                    "current_actions": [{"title": "置顶评论补充路线", "action": "补预算、时长和适合人群。"}],
                    "next_iteration": [{"title": "下一篇改成午休自救清单", "change": "封面写 3 个可复制动作。"}],
                },
                "audience_keywords": {
                    "target_audience": ["打工人", "午休想放松的人"],
                    "keywords": ["工作日午休", "打工人自救"],
                    "hot_tags": ["咖啡厅日常"],
                    "title_patterns": ["打工人午休去哪"],
                    "match_diagnosis": "目标人群明确，关键词还可以更长尾。",
                },
                "scores": {
                    "入口吸引力": {"score": 76, "evidence": "封面有场景感。", "confidence": "中"},
                    "标题搜索力": {"score": 68, "evidence": "有场景词。", "confidence": "中"},
                    "正文承接力": {"score": 82, "evidence": "开头真实。", "confidence": "高"},
                    "收藏价值": {"score": 61, "evidence": "清单信息偏少。", "confidence": "中"},
                    "评论互动": {"score": 58, "evidence": "评论钩子偏温和。", "confidence": "中"},
                    "转化/关注潜力": {"score": 64, "evidence": "系列感可强化。", "confidence": "低"},
                },
                "diagnosis": {
                    "problems": [{"title": "收藏价值偏弱", "evidence": "收藏数低于点赞。"}],
                    "hypotheses": [{"title": "情绪共鸣强", "evidence": "点赞表现更突出。"}],
                    "risks": [{"title": "审慎表达", "risk": "不要夸大疗愈效果。"}],
                },
                "experiments": [
                    {
                        "title": "下一篇改成午休自救清单",
                        "change": "封面写 3 个可复制动作。",
                        "success_metric": "收藏率提升",
                    }
                ],
            }
        )
        output = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False)
        output.close()
        self.addCleanup(lambda: Path(output.name).unlink(missing_ok=True))

        result = self.run_python(["scripts/generate_review_report.py", "--input", review_path, "--output", output.name])
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")
        html = Path(output.name).read_text(encoding="utf-8")
        self.assertIn("工作日中午，我偷偷去咖啡厅充了个电", html)
        self.assertIn("data:image/png;base64", html)
        self.assertIn("<svg", html)
        self.assertIn("数据结论", html)
        self.assertIn("流量来自哪里，卡在哪一段", html)
        self.assertIn("封面和标题是否吸引点击", html)
        self.assertIn("目标人群与关键词是否匹配", html)
        self.assertIn("当前这篇还能补救什么", html)
        self.assertIn("下一篇怎么迭代", html)
        self.assertIn("参考评分（六维评分弱化）", html)
        self.assertIn("六维雷达图（附录）", html)
        self.assertIn("指标柱状图", html)
        self.assertIn("互动占比饼图", html)
        self.assertIn("连线图", html)
        self.assertIn("小眼睛/观看", html)
        self.assertIn("打工人", html)
        self.assertIn("下一篇改成午休自救清单", html)
        self.assertNotIn("总分 / 100", html)
        for forbidden in ("cdn.jsdelivr", "cdnjs", "unpkg"):
            self.assertNotIn(forbidden, html)

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
        self.assertIn("发布后复盘 HTML 看板", readme)
        self.assertIn("复盘报告脚本", readme)
        self.assertIn("小眼睛/观看", readme)
        self.assertIn("数据结论", readme)
        self.assertIn("流量漏斗", readme)
        self.assertIn("封面标题点击诊断", readme)
        self.assertIn("目标人群与关键词匹配", readme)
        self.assertIn("六维评分保留但弱化", readme)
        self.assertIn("六维雷达图", readme)
        self.assertIn("指标柱状图", readme)
        self.assertIn("互动占比饼图", readme)
        self.assertIn("连线图", readme)
        self.assertIn("下一篇实验卡", readme)
        self.assertIn("纯文本降级", readme)
        self.assertIn("ASCII 示例图", readme)
        self.assertIn("Markdown 降级版", readme)
        self.assertIn("Python 不可用", readme)
        for needle in (
            "风景图生成治愈文案",
            "AI 插画生成热梗风笔记",
            "只有主题，规划完整图文笔记",
            "直接生成图片",
            "发布前风险检查和改写",
            "发布后复盘并生成 HTML 看板",
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
            "references/fallback_outputs.md": [
                "脚本不可用",
                "scripts/ 目录缺失",
                "python3 不存在",
                "ASCII 示例图",
                "这只是示意图，不是真实生成图片",
                "发布后复盘报告（Markdown 降级版）",
                "小眼睛/观看数",
                "不完整流量诊断",
                "数据结论",
                "流量漏斗表",
                "封面标题点击诊断表",
                "目标人群与关键词匹配表",
                "附录参考评分",
                "六维评分表",
                "下一篇实验卡表",
                "风险提醒表",
            ],
            "references/post_publish_review.md": [
                "发布后复盘",
                "手动数据",
                "截图识别",
                "单篇链接",
                "主页链接",
                "公开可见信息",
                "小眼睛/观看数必问",
                "流量漏斗诊断",
                "封面标题点击诊断",
                "目标人群与关键词匹配",
                "六维评分保留但弱化",
                "六维评分",
                "六维雷达图",
                "指标柱状图",
                "互动占比饼图",
                "连线图",
                "下一篇实验卡",
                "Markdown 降级版",
            ],
            "references/risk_checklist.md": ["AI 生成内容", "发布前检查清单"],
        }
        for relative_path, needles in checks.items():
            text = (ROOT / relative_path).read_text(encoding="utf-8")
            for needle in needles:
                self.assertIn(needle, text, f"{relative_path} 缺少 {needle}")


if __name__ == "__main__":
    unittest.main()
