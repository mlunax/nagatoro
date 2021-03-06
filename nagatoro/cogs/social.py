from math import sqrt, floor, ceil
from datetime import datetime

from asyncio import TimeoutError
from discord import Message, Color
from discord.errors import Forbidden
from discord.ext.commands import (
    Cog,
    Context,
    command,
    group,
    cooldown,
    BucketType,
)

from nagatoro.converters import Member
from nagatoro.objects import Embed
from nagatoro.utils import aenumerate
from nagatoro.db import Guild, User, Mute, Warn


class Social(Cog):
    """Social commands"""

    def __init__(self, bot):
        self.bot = bot

    @command(name="profile")
    @cooldown(rate=2, per=10, type=BucketType.user)
    async def profile(self, ctx: Context, *, member: Member = None):
        """User's profile"""

        if not member:
            member = ctx.author

        user, _ = await User.get_or_create(id=member.id)
        # Calculate current level progress:
        # (exp - curr lvl req) * 100 / (curr lvl req - next lvl req)
        current_level_exp = (user.level * 4) ** 2
        next_level_exp = ((user.level + 1) * 4) ** 2
        progress = round(
            (user.exp - current_level_exp) * 100 / (next_level_exp - current_level_exp)
        )
        # Find position of profile in global user ranking
        rank = (await User.all().order_by("-exp")).index(user)

        embed = Embed(ctx, title=f"{member.name}'s profile", color=member.color)
        embed.set_thumbnail(url=member.avatar_url)

        embed.add_fields(
            ("Rank", str(rank + 1)),
            ("Level", f"{user.level}"),
            ("Experience", f"{user.exp}/{next_level_exp} ({progress}%)"),
            ("Balance", f"{user.balance} coins"),
        )

        if mutes := await Mute.filter(
            guild__id=ctx.guild.id, user__id=member.id
        ).count():
            embed.add_field(name="Mutes", value=str(mutes))
        if warns := await Warn.filter(
            guild__id=ctx.guild.id, user__id=member.id
        ).count():
            embed.add_field(name="Warns", value=str(warns))

        await ctx.send(embed=embed)

    @command(name="balance", aliases=["bal", "money"])
    @cooldown(rate=5, per=10, type=BucketType.user)
    async def balance(self, ctx: Context, *, member: Member = None):
        """Coin balance"""

        if not member:
            member = ctx.author

        user, _ = await User.get_or_create(id=member.id)
        await ctx.send(f"{member.name}'s balance: **{user.balance}**")

    @command(name="level", aliases=["lvl"])
    @cooldown(rate=5, per=10, type=BucketType.user)
    async def level(self, ctx: Context, *, member: Member = None):
        """User's level"""

        if not member:
            member = ctx.author

        user, _ = await User.get_or_create(id=member.id)
        await ctx.send(f"{member.name}'s level: **{user.level}**")

    @group(name="ranking", aliases=["top", "baltop"], invoke_without_command=True)
    @cooldown(rate=2, per=30, type=BucketType.guild)
    async def ranking(self, ctx: Context):
        """User ranking

        Use 'baltop' for quicker access to the balance ranking
        """

        if ctx.invoked_with == "baltop":
            return await self.ranking_balance.__call__(ctx)

        await self.ranking_level.__call__(ctx)

    @ranking.command(name="level", aliases=["lvl"])
    @cooldown(rate=2, per=30, type=BucketType.guild)
    async def ranking_level(self, ctx: Context):
        """User ranking, by level"""

        embed = Embed(ctx, title="Level Ranking", description="", color=Color.blue())

        await ctx.trigger_typing()
        async for pos, i in aenumerate(User.all().order_by("-exp").limit(10), start=1):
            user = await self.bot.fetch_user(i.id)
            embed.description += f"{pos}. **{user}**: {i.level} ({i.exp} exp)\n"

        await ctx.send(embed=embed)

    @ranking.command(name="balance", aliases=["bal", "money"])
    @cooldown(rate=2, per=30, type=BucketType.guild)
    async def ranking_balance(self, ctx: Context):
        """User ranking, sorted by balance"""

        embed = Embed(ctx, title="Balance Ranking", description="", color=Color.blue())

        await ctx.trigger_typing()
        async for pos, i in aenumerate(
            User.all().order_by("-balance").limit(10), start=1
        ):
            user = await self.bot.fetch_user(i.id)
            embed.description += f"{pos}. **{user}**: {i.balance} coins\n"

        await ctx.send(embed=embed)

    @command(name="pay", aliases=["give", "transfer"])
    @cooldown(rate=2, per=10, type=BucketType.user)
    async def pay(self, ctx: Context, amount: int, *, member: Member):
        """Give coins to someone

        You can't give money to yourself or any bots.
        Transfer amount should be more than 0.
        """

        if member == ctx.author or member.bot:
            return await ctx.send("You can give money to other users only.")
        if amount <= 0:
            return await ctx.send("You need to pay at least 1 coin.")

        user, _ = await User.get_or_create(id=ctx.author.id)

        if user.balance < amount:
            return await ctx.send(
                f"Not enough funds, you have "
                f"{user.balance} coins ({amount - user.balance} missing)."
            )

        embed = Embed(
            ctx,
            title="Transfer",
            description=f"You are about to give **{amount}** "
            f"coin(s) to {member.mention}, are you sure?",
        )
        message = await ctx.send(embed=embed)
        await message.add_reaction("✅")

        try:
            await self.bot.wait_for(
                "reaction_add",
                timeout=30,
                check=lambda r, u: u == ctx.message.author and str(r.emoji) == "✅",
            )
        except TimeoutError:
            embed.description = "Transfer cancelled."
            return await message.edit(embed=embed)

        target_user, _ = await User.get_or_create(id=member.id)
        user.balance -= amount
        target_user.balance += amount
        await user.save()
        await target_user.save()

        try:
            await message.clear_reactions()
        except Forbidden:
            pass

        embed.description = f"Transferred **{amount}** coin(s) " f"to {member.mention}"
        await message.edit(embed=embed)

    @command(name="daily", aliases=["dly"])
    async def daily(self, ctx: Context, member: Member = None):
        """Daily coin reward

        Mention someone to give your them your reward.
        Can be used once every 23 hours.
        Streak gives you more coins over time, but will be lost after 2 days of inactivity.
        """

        if member and member.bot:
            return await ctx.send("You can't give points to a bot!")

        user, _ = await User.get_or_create(id=ctx.author.id)

        def hours_til_next_daily() -> int:
            return ceil(
                (user.next_daily.timestamp() - datetime.utcnow().timestamp()) / 3600
            )

        if not user.daily_available:
            try:
                await ctx.send(
                    f"Your next daily will be available in "
                    f"**{hours_til_next_daily()} hour(s)**. Current streak: "
                    f"**{user.daily_streak}**."
                )
            except Forbidden:
                pass
            return

        expired = "(lost streak)" if user.daily_streak_expired else ""
        if user.daily_streak_expired:
            user.daily_streak = 1
        else:
            user.daily_streak += 1

        bonus = floor(sqrt(user.daily_streak) * 20)
        user.last_daily = datetime.utcnow()

        if member:
            target_user, _ = await User.get_or_create(id=member.id)
        else:
            target_user = user
        target_user.balance += 100 + bonus

        await user.save()
        if user != target_user:
            await target_user.save()

        embed = Embed(ctx, title="Daily", color=ctx.author.color)
        if user == target_user:
            embed.description = (
                f"You received **{100 + bonus}** daily points\n"
                f"Streak: **{user.daily_streak}** {expired}\n"
                f"Come back in **{hours_til_next_daily()} hour(s)** "
                f"to continue your streak!"
            )
        else:
            embed.description = (
                f"You gave your **{100 + bonus}** daily points "
                f"to {member.mention}\n"
                f"Streak: **{user.daily_streak}** {expired}\n"
                f"Come back in **{hours_til_next_daily()} hour(s)** "
                f"to continue your streak!"
            )

        try:
            await ctx.send(embed=embed)
        except Forbidden:
            pass

    @Cog.listener()
    async def on_message(self, message: Message):
        if (
            message.author.bot
            or len(message.content) <= 5
            or "spam" in message.channel.name.lower()
        ):
            # TODO: Make better spam filter.
            return

        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return

        user, _ = await User.get_or_create(id=ctx.author.id)
        user.exp += 1
        await user.save()

        if user.level != (new_level := floor(sqrt(user.exp) / 4)):
            user.level = new_level
            bonus = floor(sqrt(user.level) * 100)
            user.balance += bonus
            await user.save()

            if user.level < 5:
                return

            # Level up message, don't send if the guild has them turned off
            guild, _ = await Guild.get_or_create(id=ctx.guild.id)
            if not guild.level_up_messages:
                return

            try:
                await ctx.send(
                    f"Congrats **{ctx.author.name}**, "
                    f"you levelled up to **level {user.level}** "
                    f"and got a bonus of **{bonus} points**."
                )
            except Forbidden:
                pass

            # TODO: Let the admin choose if they want embed or text level ups
            # embed = Embed(ctx, title="Level up!")
            # embed.set_thumbnail(url=ctx.author.avatar_url)
            # embed.description = (
            #     f"Congratulations, {ctx.author.mention}! "
            #     f"You have advanced to **level {user.level}** "
            #     f"and got a bonus of **{bonus} points**."
            # )
            #
            # level_up_message = await ctx.send(embed=embed)
            # await level_up_message.delete(delay=30)


def setup(bot):
    bot.add_cog(Social(bot))
