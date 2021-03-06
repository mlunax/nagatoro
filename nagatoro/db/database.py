from datetime import datetime, timedelta

from tortoise import Tortoise
from tortoise.models import Model
from tortoise.fields import (
    IntField,
    BigIntField,
    TextField,
    DatetimeField,
    BooleanField,
    ForeignKeyField,
    ForeignKeyRelation,
    ReverseRelation,
)


class Guild(Model):
    id = BigIntField(pk=True)
    prefix = TextField(null=True)
    mute_role = BigIntField(null=True)
    level_up_messages = BooleanField(default=True)
    moderators: ReverseRelation["Moderator"]
    mutes: ReverseRelation["Mute"]
    warns: ReverseRelation["Warn"]

    class Meta:
        table = "guilds"

    def __str__(self):
        return f"<Guild id:{self.id} prefix:{self.prefix} muterole:{self.mute_role}>"


class User(Model):
    id = BigIntField(pk=True)
    exp = IntField(default=0)
    level = IntField(default=0)
    balance = IntField(default=0)
    daily_streak = IntField(default=0)
    last_daily = DatetimeField(null=True)
    mutes: ReverseRelation["Mute"]
    warns: ReverseRelation["Warn"]

    @property
    def next_daily(self):
        if not self.last_daily:
            return None

        return datetime.fromtimestamp(
            (self.last_daily + timedelta(hours=23)).timestamp()
        )

    @property
    def daily_available(self):
        if not self.last_daily:
            return True

        return datetime.utcnow().timestamp() > self.next_daily.timestamp()

    @property
    def daily_streak_expired(self):
        if not self.last_daily:
            return None

        return (
            datetime.utcnow().timestamp()
            > (self.last_daily + timedelta(days=2)).timestamp()
        )

    class Meta:
        table = "users"

    def __str__(self):
        return (
            f"<User id:{self.id} exp:{self.exp} "
            f"level:{self.level} bal:{self.balance}>"
        )


class Moderator(Model):
    id = IntField(pk=True)
    user: ForeignKeyRelation[User] = ForeignKeyField(
        "models.User", related_name="moderator_on"
    )
    guild: ForeignKeyRelation[Guild] = ForeignKeyField(
        "models.Guild", related_name="moderators"
    )
    title = TextField(null=True)

    class Meta:
        table = "moderators"


class Mute(Model):
    id = IntField(pk=True)
    moderator = BigIntField()
    reason = TextField(null=True)
    start = DatetimeField(auto_now_add=True)
    end = DatetimeField()
    active = BooleanField(default=True)
    user: ForeignKeyRelation[User] = ForeignKeyField(
        "models.User", related_name="mutes"
    )
    guild: ForeignKeyRelation[Guild] = ForeignKeyField(
        "models.Guild", related_name="mutes"
    )

    class Meta:
        table = "mutes"

    def __str__(self):
        return (
            f"<Mute id:{self.id} moderator:{self.moderator} "
            f"reason:'{self.reason}' start:{self.start} end:{self.end} "
            f"active:{self.active} user:{self.user.id} guild:{self.guild.id}>"
        )


class Warn(Model):
    id = IntField(pk=True)
    moderator = BigIntField()
    reason = TextField(null=True)
    when = DatetimeField(auto_now_add=True)
    user: ForeignKeyRelation[User] = ForeignKeyField(
        "models.User", related_name="warns"
    )
    guild: ForeignKeyRelation[Guild] = ForeignKeyField(
        "models.Guild", related_name="warns"
    )

    class Meta:
        table = "warns"

    def __str__(self):
        return (
            f"<Warn id:{self.id} moderator:{self.moderator} "
            f"reason:'{self.reason}' datetime:{self.when} "
            f"user:{self.user.id} guild:{self.guild.id}>"
        )


async def init_database(db_url: str):
    # logging.info("Initializing database connection...")
    await Tortoise.init(
        db_url=db_url,
        modules={"models": [__name__]},
    )
    await Tortoise.generate_schemas()
    # logging.info("Successfully connected to database")
