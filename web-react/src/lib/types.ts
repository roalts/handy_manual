// Types for the parts of the API that the AnswerResponse schema doesn't cover, written from
// src/copilot_contracts/ (answer.py, work_orders.py) and specs/contracts/http-api.md.

export type * from "./contract";
import type { AnswerResponse, PartLine, WorkOrderSuggestion } from "./contract";

export interface Identity {
  user_id: string;
  name: string;
  groups: string[];
}

export interface DevUser {
  user_id: string;
  name: string;
  title: string;
  groups: string[];
}

export type GroupWords = Record<string, string>;

export interface PreviousTurn {
  answer_id: string;
  question: string;
  asset_id?: string | null;
}

export interface AskRequest {
  question: string;
  asset_id?: string | null;
  clarification_of?: string | null;
  previous?: PreviousTurn | null;
}

/** The answer on screen and the request that produced it. Held in memory only. */
export interface Turn {
  request: AskRequest;
  response: AnswerResponse;
}

export interface SourceView {
  passage_id: string;
  doc_id: string;
  title: string;
  doc_type: string;
  revision: string | null;
  issue_date: string | null;
  status: string;
  superseded_by: string | null;
  locator: string;
  lang: string;
  text_original: string;
  text_en: string | null;
  page: number | null;
  page_image_url: string | null;
  ocr: boolean;
  possibly_stale: boolean;
}

export type DraftStatus = "draft" | "pending_approval" | "approved" | "rejected" | "submitted";
export type Priority = "low" | "medium" | "high";
export type TargetSystem = "maintpro" | "servio";

export interface WorkOrderDraft {
  draft_id: string;
  created_by: string;
  created_at: string;
  answer_id: string | null;
  asset_id: string;
  target_system: TargetSystem;
  fault_code: string | null;
  summary: string;
  work_steps: string;
  required_certification: string[];
  parts: PartLine[];
  campaign_code: string | null;
  priority: Priority;
  needs_specialist: boolean;
  return_visit: boolean;
  citations: string[];
  status: DraftStatus;
  approval_reasons: string[];
  eligible_approvers: string[];
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  idempotency_key: string;
  external_ref: string | null;
}

/** The fields PATCH /api/work-orders/{id} accepts. */
export interface DraftEdits {
  fault_code: string | null;
  summary: string;
  work_steps: string;
  priority: Priority;
  parts: { part_number: string; quantity: number }[];
  needs_specialist: boolean;
  return_visit: boolean;
}

export interface CreateDraftRequest {
  answer_id: string;
  suggestion: WorkOrderSuggestion;
  asset_id?: string;
}
