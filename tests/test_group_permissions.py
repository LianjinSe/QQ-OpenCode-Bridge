from dataclasses import replace

import pytest
from conftest import eventually, message

from qqbot.config import ConfigError
from qqbot.models import Context
from qqbot.policy import permissions_for, shell_is_readonly

ADMIN = 10001
USERS = frozenset({11, 12, ADMIN})


@pytest.mark.parametrize("action", ["websearch", "webfetch", "docs_search", "filesystem_read_file"])
async def test_group_non_file_actions_default_allow(harness, action):
    async with harness(
        allowed_users=USERS,
        superadmin_user_id=ADMIN,
        group_readonly_mcp_actions=frozenset({"docs_search", "filesystem_read_file"}),
    ) as (bridge, nap, op):
        op.mode = "permission"
        op.permission_action = action
        op.permission_resources = ["query"]
        await nap.emit(message("查询资料", group=22, at=True))
        await eventually(lambda: bool(nap.sent))
        assert not any("/approve " in text for text in nap.texts())
        assert op.decisions[0][2] == "once"
        sid = op.prompts[0]["sessionID"]
        rules = op.sessions[sid]["permissions"]
        assert any(r["action"] == action and r["effect"] == "allow" for r in rules)
        assert op.instructions[sid]["qq-bridge.identity"].splitlines() == [
            "机器人 QQ 号：777。当前发送者 QQ 号：11。",
            "当前会话类型：群聊，群号：22。",
            "当前发送者身份：普通授权用户。",
        ]
        await eventually(lambda: bridge.store.latest(Context(777, 11, 22))["status"] == "done")


async def test_group_file_edit_mentions_admin_and_only_same_group_admin_can_approve(harness):
    async with harness(allowed_users=USERS, superadmin_user_id=ADMIN) as (bridge, nap, op):
        op.mode = "permission"
        op.permission_in_child = True
        await nap.emit(message("修改文件", group=22, at=True))
        await eventually(lambda: bool(nap.sent))
        assert nap.sent[0]["group_id"] == "22"
        assert nap.sent[0]["message"][0] == {"type": "at", "data": {"qq": str(ADMIN)}}
        job = bridge.store.latest(Context(777, 11, 22))
        code = bridge.store.pending_for(job["id"])[0]["code"]
        for user, group in [(11, 22), (12, 22), (ADMIN, 23), (ADMIN, None)]:
            await nap.emit(message(f"/approve {code}", user=user, group=group, at=bool(group)))
        await eventually(lambda: len(nap.sent) >= 5)
        assert op.decisions == []
        await nap.emit(message("/status", user=ADMIN, group=22, at=True))
        await eventually(lambda: any(code in t and "等点头或回答" in t for t in nap.texts()))
        # The admin can reply without an @bot mention; the request remains group-scoped.
        await nap.emit(message(f"/approve\t{code}", user=ADMIN, group=22))
        await eventually(lambda: bool(op.decisions))
        assert op.decisions[0][0].startswith("ses_child_")
        assert op.decisions[0][2] == "once"
        await eventually(lambda: bridge.store.job(job["id"])["status"] == "done")
        results = [
            p
            for p in nap.sent
            if any(
                s.get("type") == "text" and "回复：修改文件" in s["data"]["text"]
                for s in p["message"]
            )
        ]
        assert results[-1]["message"][0]["data"]["qq"] == "11"


async def test_unknown_mcp_needs_admin_rejection(harness):
    async with harness(allowed_users=USERS, superadmin_user_id=ADMIN) as (bridge, nap, op):
        op.mode = "permission"
        op.permission_action = "custom_manage"
        await nap.emit(message("调用未知工具", group=22, at=True))
        await eventually(lambda: bool(nap.sent))
        assert op.decisions == []
        assert nap.sent[0]["message"][0]["data"]["qq"] == str(ADMIN)
        job = bridge.store.latest(Context(777, 11, 22))
        code = bridge.store.pending_for(job["id"])[0]["code"]
        await nap.emit(message(f"/reject {code}", user=ADMIN, group=22))
        await eventually(lambda: bool(op.decisions))
        assert op.decisions[0][2] == "reject"


async def test_readonly_shell_allowed_but_output_redirection_needs_admin(harness):
    async with harness(allowed_users=USERS, superadmin_user_id=ADMIN) as (bridge, nap, op):
        op.mode = "permission"
        op.permission_action = "shell"
        op.permission_resources = ["pwd"]
        op.permission_metadata = {"command": "pwd"}
        await nap.emit(message("查看目录", group=22, at=True))
        await eventually(lambda: len(nap.sent) == 1)
        assert op.decisions[-1][2] == "once"
        op.permission_metadata = {"command": "pwd > important.txt"}
        await nap.emit(message("把结果写入文件", group=22, at=True))
        await eventually(lambda: len(nap.sent) >= 2)
        assert len(op.decisions) == 1
        assert nap.sent[-1]["message"][0]["data"]["qq"] == str(ADMIN)
        assert "/approve " in nap.texts()[-1]


async def test_full_original_tool_input_overrides_safe_scanner_fragment(harness):
    async with harness(allowed_users=USERS, superadmin_user_id=ADMIN) as (bridge, nap, op):
        op.mode = "permission"
        op.permission_action = "shell"
        op.permission_resources = ["ls"]
        op.permission_metadata = {"command": "ls"}
        op.permission_source = {"type": "tool", "messageID": "msg_tool", "id": "tool_1"}
        await nap.emit(message("运行命令", group=22, at=True))
        await eventually(lambda: bool(op.prompts))
        sid = op.prompts[0]["sessionID"]
        op.messages[sid].append(
            {
                "id": "msg_tool",
                "type": "assistant",
                "content": [
                    {
                        "type": "tool",
                        "id": "tool_1",
                        "name": "shell",
                        "state": {
                            "status": "running",
                            "input": {"command": "ls; rm important.txt"},
                        },
                    }
                ],
            }
        )
        await eventually(lambda: bool(nap.sent))
        assert op.decisions == []
        assert nap.sent[0]["message"][0]["data"]["qq"] == str(ADMIN)


async def test_admin_group_file_change_is_automatically_approved(harness):
    async with harness(allowed_users=USERS, superadmin_user_id=ADMIN) as (bridge, nap, op):
        op.mode = "permission"
        await nap.emit(message("修改文件", user=ADMIN, group=22, at=True))
        await eventually(lambda: bool(nap.sent))
        assert op.decisions[0][2] == "once"
        assert not any("/approve " in text for text in nap.texts())
        job = bridge.store.latest(Context(777, ADMIN, 22))
        assert bridge.store.pending_for(job["id"]) == []


async def test_admin_cannot_answer_another_members_task_question(harness):
    async with harness(allowed_users=USERS, superadmin_user_id=ADMIN) as (bridge, nap, op):
        op.mode = "form"
        await nap.emit(message("询问任务细节", group=22, at=True))
        await eventually(lambda: bool(nap.sent))
        assert nap.sent[0]["message"][0]["data"]["qq"] == "11"
        job = bridge.store.latest(Context(777, 11, 22))
        code = bridge.store.pending_for(job["id"])[0]["code"]
        await nap.emit(message(f"/answer {code} 1", user=ADMIN, group=22, at=True))
        await eventually(lambda: len(nap.sent) >= 2)
        state = bridge.store.interaction(code)
        assert state["answers"] == "{}"
        assert op.answers == []


@pytest.mark.parametrize(
    "command",
    [
        "rm a",
        "mv a b",
        "cp a b",
        "python -c 'print(1)'",
        "ls > file",
        "cat a >> b",
        "ls; rm a",
        "echo $(rm a)",
        "ls | tee output",
        "bash script.sh",
        "find . -delete",
        "sed -i 's/a/b/' file",
        "git status; rm a",
        "ls `rm a`",
    ],
)
def test_file_mutation_or_unknown_shell_is_not_readonly(command):
    assert not shell_is_readonly(command)


@pytest.mark.parametrize("command", ["pwd", "ls -la", "cat README.md", "head -n 5 a", "git status"])
def test_known_inspection_shell_is_readonly(command):
    assert shell_is_readonly(command)


def test_readonly_mcp_configuration_cannot_allow_edit_or_arbitrary_patterns(harness, tmp_path):
    from qqbot.config import Config

    base = Config(
        napcat_url="ws://127.0.0.1:3001",
        napcat_token="t",
        allowed_users=frozenset({ADMIN}),
        superadmin_user_id=ADMIN,
    )
    for action in ["*", "filesystem_write_file", "filesystem_delete_file", "apply_patch"]:
        with pytest.raises(ConfigError):
            replace(base, group_readonly_mcp_actions=frozenset({action})).validate()
    rules = permissions_for(
        replace(base, group_readonly_mcp_actions=frozenset({"docs_search"})),
        Context(777, 11, 22),
    )
    assert {"action": "edit", "resource": "*", "effect": "ask"} in rules
    assert {"action": "shell", "resource": "*", "effect": "ask"} in rules
