from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from backend.movies.genres import normalize_genres

UserId = Literal["lera", "nikita"]
Reaction = Literal["love", "like", "okay", "dislike", "unseen"]


class PreferencesIn(BaseModel):
    user_id: UserId
    # The interface deliberately exposes all of its mood chips as combinable.
    # Keep validation in step with it so an enthusiastic choice cannot strand a
    # person on the preferences screen with an opaque 422 response.
    moods: list[str] = Field(min_length=1, max_length=11)
    energy: Literal["low", "medium", "high"]
    max_runtime: int | None = None
    min_year: int | None = None
    disliked_genres: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("disliked_genres")
    @classmethod
    def canonical_dislikes(cls, value: list[str]) -> list[str]:
        return normalize_genres(value)


class SwipeIn(BaseModel):
    user_id: UserId
    movie_id: str
    reaction: Reaction


class UserAction(BaseModel):
    user_id: UserId


class JoinIn(UserAction):
    access_code: str | None = Field(default=None, pattern=r"^\d{6}$")


class AvoidSimilarIn(BaseModel):
    user_id: UserId
    movie_id: str = Field(min_length=1, max_length=160)


class FeedbackIn(BaseModel):
    user_id: UserId
    rating: int = Field(ge=1, le=5)


class EveningFeedbackIn(BaseModel):
    user_id: UserId
    fit: bool


class RestoreBackupIn(BaseModel):
    confirmed: bool


class PrivacyDeleteIn(BaseModel):
    confirmation: str = Field(min_length=1, max_length=64)


class OllamaCandidate(BaseModel):
    id: str
    explanation_lera: str = Field(max_length=220)
    explanation_nikita: str = Field(max_length=220)
    compromise: str = Field(max_length=300)


class OllamaResponse(BaseModel):
    candidates: list[OllamaCandidate] = Field(min_length=1, max_length=8)

    @field_validator("candidates")
    @classmethod
    def unique_ids(cls, value: list[OllamaCandidate]) -> list[OllamaCandidate]:
        ids = [item.id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate movie ids")
        return value
