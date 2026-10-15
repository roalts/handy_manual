-- Items the latest run no longer raises (the source or the rule changed) are obsolete, not open.
ALTER TABLE control.review_items DROP CONSTRAINT review_items_status_check;
ALTER TABLE control.review_items ADD CONSTRAINT review_items_status_check
    CHECK (status IN ('open', 'resolved', 'obsolete'));
