from pydantic import BaseModel, Field


class TBullet(BaseModel):
    text: str
    fact_ids: list[str] = Field(description="Ids (e.g. F12) of the facts this bullet is derived from")


class TRole(BaseModel):
    fact_id: str = Field(description="Id of the EMPLOYMENT fact")
    bullets: list[TBullet] = Field(default_factory=list)


class TProject(BaseModel):
    fact_id: str = Field(description="Id of the PROJECT fact")
    bullets: list[TBullet] = Field(default_factory=list)


class TSkill(BaseModel):
    name: str
    fact_id: str = Field(description="Id of the SKILL fact")


class TailoredResume(BaseModel):
    summary: str = ""
    summary_fact_ids: list[str] = Field(default_factory=list)
    roles: list[TRole] = Field(default_factory=list)
    projects: list[TProject] = Field(default_factory=list)
    skills: list[TSkill] = Field(default_factory=list)
    education_fact_ids: list[str] = Field(default_factory=list)
    certification_fact_ids: list[str] = Field(default_factory=list)
    keywords_used: list[str] = Field(default_factory=list)
    unsupported_requirements: list[str] = Field(default_factory=list)
    needs_confirmation: list[str] = Field(default_factory=list)
    emphasis_notes: list[str] = Field(default_factory=list, description="What was prioritised and why")


class JudgeItem(BaseModel):
    bullet: str
    flagged: bool
    reason: str = ""


class JudgeResult(BaseModel):
    items: list[JudgeItem] = Field(default_factory=list)


class TailorOptions(BaseModel):
    tone: str = "balanced"  # conservative | balanced | targeted
    length: str = "flexible"  # one_page | two_page | flexible
    include_projects: bool = True
    exclude_project_ids: list[int] = Field(default_factory=list)
    cover_letter: bool = False
    motivation: str = ""
    ordering: str = "relevance"  # relevance | preserve
    spelling: str = "uk"  # uk | us
    date_format: str = "MMM YYYY"  # MMM YYYY | MM/YYYY | YYYY
    template: str = "classic"  # classic | modern
