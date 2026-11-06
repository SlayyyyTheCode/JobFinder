"""Structured-output schemas for resume extraction. Kept free of dict fields so they map
cleanly to Gemini response_schema (and other providers' JSON schema modes)."""
from typing import Optional

from pydantic import BaseModel, Field


class XContact(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: list[str] = Field(default_factory=list)


class XEmployment(BaseModel):
    employer: str
    title: str
    location: str = ""
    start: str = Field("", description="YYYY-MM or YYYY exactly as supported by the resume")
    end: str = Field("", description="YYYY-MM, YYYY, or 'Present'")
    achievements: list[str] = Field(default_factory=list, description="Bullets copied verbatim")
    confidence: float = Field(1.0, description="0-1 confidence this entry was parsed correctly")


class XEducation(BaseModel):
    institution: str
    qualification: str = ""
    field: str = ""
    start: str = ""
    end: str = ""
    grade: str = ""
    confidence: float = 1.0


class XSkill(BaseModel):
    name: str
    category: str = Field("", description="e.g. language, framework, cloud, tool, domain, soft")
    level: str = Field("unspecified", description="expert|proficient|familiar|unspecified — only if stated")


class XCertification(BaseModel):
    name: str
    issuer: str = ""
    date: str = ""


class XProject(BaseModel):
    name: str
    description: str = ""
    bullets: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)


class ExtractedResume(BaseModel):
    contact: XContact = Field(default_factory=XContact)
    summary: str = ""
    employment: list[XEmployment] = Field(default_factory=list)
    education: list[XEducation] = Field(default_factory=list)
    skills: list[XSkill] = Field(default_factory=list)
    certifications: list[XCertification] = Field(default_factory=list)
    projects: list[XProject] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    awards: list[str] = Field(default_factory=list)
    publications: list[str] = Field(default_factory=list)
    raw_text: Optional[str] = Field(None, description="Only when transcribing a scanned document: full plain text")
