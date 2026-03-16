

 



Fetched 4 resources

Let me fetch the Bot API inline mode page and the mentions/groups documentation more directly. 



Fetched 4 resources

Now let me look at the current bot code to understand how mentions/group interactions are currently handled. 

Explore bot group/mention handling

Read [](file:///c%3A/Users/lohjo/source/repos/jwj2026/telegram_bot.py)

Read [](file:///c%3A/Users/lohjo/source/repos/jwj2026/config.py)

Searched for regex `message_entities|MessageEntity|entities|mention|@|group|GROUP|inline|parse_mode_html`, 20 results

Searched for regex `group|chat_type|GROUP_CHAT|private|supergroup` (`**/*.py`), 1 result

Searched for regex `entities|MessageEntity|mention|groups?|inline|entity` (`**/telegram_bot.py`), no results

Searched for regex `effective_chat|chat_id|chat_type|is_group` (`**/*.py`), 19 results

Read [](file:///c%3A/Users/lohjo/source/repos/jwj2026/tests/test_telegram_bot.py#1-1), lines 1 to 150

Read [](file:///c%3A/Users/lohjo/source/repos/jwj2026/pipeline/formatter.py)

Read [](file:///c%3A/Users/lohjo/source/repos/jwj2026/pipeline/translator.py#1-1), lines 1 to 100

Read [](file:///c%3A/Users/lohjo/source/repos/jwj2026/telegram_bot.py#1-1), lines 1 to 100

Read [](file:///c%3A/Users/lohjo/source/repos/jwj2026/config.py#1-1), lines 1 to 80

Read [](file:///c%3A/Users/lohjo/source/repos/jwj2026/telegram_bot.py#100-100), lines 100 to 350

Read [](file:///c%3A/Users/lohjo/source/repos/jwj2026/telegram_bot.py#350-350), lines 350 to 600

Read [](file:///c%3A/Users/lohjo/source/repos/jwj2026/telegram_bot.py#600-600), lines 600 to 680

Now I have all the context needed. Let me save the plan and present findings. 

Created memory file [](file:///c%3A/Users/lohjo/AppData/Roaming/Code/User/workspaceStorage/94bc8e3bf64703f4ef84f5b5e9f92053/GitHub.copilot-chat/memory-tool/memories/ODhlOThlZTctOThmZi00ZTM2LTkzZjktNDU3MmRlNjQ3ZjBm/plan.md)

## Plan: Enable @mention Bot Invocation in Groups

**TL;DR**: There are three distinct mechanisms for triggering a bot via `@username` in Telegram. The current SENTINEL bot supports none of them for group chats. The recommended approach is to add group mention detection (Phase 1) and optionally inline mode (Phase 2).

---

### Background: The `document` constructor

The page you referenced (`core.telegram.org/constructor/document`) describes the **MTProto schema for file documents** (id, access_hash, mime_type, thumbnails, etc.). It is not related to bot mentions — it's the low-level wire format for file metadata. The relevant APIs for mentions are the **Bot API's `Update`, `MessageEntity`, and `InlineQuery`** objects.

---

### Three mechanisms for `@botname` invocation

**1. Inline Queries** — user types `@jwjbot query` in the message input field
- Triggers an `InlineQuery` update (separate from regular messages)
- Bot responds via `answerInlineQuery()` with a list of results displayed as a dropdown
- User selects a result → it's sent to the current chat
- **Requires**: enabling via BotFather (`/setinline`) + an `InlineQueryHandler`
- **Not currently implemented** in SENTINEL

**2. @mention in group message text** — user sends `@jwjbot check this article`
- Creates a `MessageEntity` with `type="mention"` in the message's `entities` array
- **Privacy Mode** (ON by default) blocks this — bot does NOT receive the message unless:
  - Privacy mode is **disabled** (bot sees all group messages), OR
  - The bot is a **group admin** (admins always receive everything)
- To detect: parse `update.message.entities`, find entities of type `mention`, check if the username matches your bot
- **Not currently implemented** — current `handle_text` has no entity parsing

**3. Commands with bot suffix** — `/detect@jwjbot some text`
- Works in groups even with privacy mode ON (Telegram routes commands explicitly addressed to a bot)
- **Already partially works** via existing `CommandHandler("detect", ...)`, though `python-telegram-bot` handles the `@suffix` stripping automatically

---

### Steps

**Phase 1: Group @mention detection**

1. **Choose privacy mode strategy**:
   - **Option A** — Disable privacy mode via BotFather `/setprivacy` → bot sees ALL group messages → filter for mentions in code (simpler, but higher load + privacy trade-off)
   - **Option B** — Keep privacy mode ON → make bot a group admin → it receives all messages → filter for mentions (recommended for a moderation bot like SENTINEL)

2. Add `BOT_USERNAME` constant to config.py (e.g., `"jwjbot"`)

3. In telegram_bot.py, create a mention-aware filter or modify `handle_text()` to check `update.message.entities` for `type="mention"` matching `BOT_USERNAME`

4. Ensure `CommandHandler` instances work in groups (they do — `python-telegram-bot` already strips `@botname` from `/command@botname`)

**Phase 2: Inline mode** (optional)

5. Enable inline mode via BotFather: `/setinline` → set placeholder text (e.g., "Paste text to check...")
6. Add `InlineQueryHandler` to the app in `start_bot()`
7. Implement `handle_inline_query()` that runs the detection pipeline and returns `InlineQueryResultArticle` results

**Relevant files**
- telegram_bot.py — add mention filter logic + optional inline query handler
- config.py — add `BOT_USERNAME` env var

**Verification**
1. Add bot to test group → send `@jwjbot check this text` → verify bot responds
2. Test `/detect@jwjbot some text` in group with multiple bots → verify routing
3. If inline mode enabled: type `@jwjbot` in input field of any chat → verify dropdown results

---

### Further Considerations

1. **Privacy mode vs admin**: For a content-moderation bot like SENTINEL, making it a **group admin** (Option B) is recommended — it gets all messages naturally and can also delete harmful content. Disable privacy mode only if you want it to work in groups where it isn't admin. **Recommendation: Option B (admin)**

2. **Inline mode scope**: Inline mode is a fundamentally different UX (results appear in a dropdown, user picks one to send). It suits content-lookup bots (like `@wiki`), but may feel awkward for a detection bot where the "result" is an analysis report. **Recommendation: defer unless there's a clear UX need**

3. **Channel support**: Channels work differently — the bot must be a channel admin and receives `channel_post` updates (not `message` updates). This requires a separate `MessageHandler(filters.ChatType.CHANNEL, ...)`. **Recommendation: add if needed, but separate from group support**