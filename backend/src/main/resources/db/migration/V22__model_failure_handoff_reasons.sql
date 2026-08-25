-- 正式调查模型失败与受控客户沟通结论必须能够原子转人工，且仍只允许封闭理由集合。
ALTER TABLE support_ticket DROP CONSTRAINT support_ticket_handoff_reason_check;
ALTER TABLE support_ticket ADD CONSTRAINT support_ticket_handoff_reason_check
    CHECK (human_handoff_reason_code IS NULL OR human_handoff_reason_code IN (
        'CUSTOMER_REQUESTED', 'CUSTOMER_REQUESTED_HUMAN', 'TOOL_RETRY_EXHAUSTED',
        'FACT_CONFLICT', 'INVALID_MODEL_OUTPUT', 'INVALID_TOOL_RESPONSE',
        'REQUIRED_FACT_MISSING', 'UNSUPPORTED_SCENARIO', 'APPROVAL_REJECTED'
    ));

ALTER TABLE agent_human_handoff_request DROP CONSTRAINT agent_human_handoff_request_reason_code_check;
ALTER TABLE agent_human_handoff_request ADD CONSTRAINT agent_human_handoff_request_reason_code_check
    CHECK (reason_code IN (
        'CUSTOMER_REQUESTED_HUMAN', 'TOOL_RETRY_EXHAUSTED', 'FACT_CONFLICT',
        'INVALID_MODEL_OUTPUT', 'INVALID_TOOL_RESPONSE', 'REQUIRED_FACT_MISSING',
        'UNSUPPORTED_SCENARIO'
    ));
