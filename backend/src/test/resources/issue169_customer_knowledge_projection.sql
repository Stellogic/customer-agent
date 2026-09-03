-- 聚焦 PostgreSQL 验证源码；必须在隔离测试数据库迁移后执行，不能作为已运行证据。
-- 数据始终回滚；后半段要求已有一张 AGENT 模式的合成测试工单及其当前 generation。
\set ON_ERROR_STOP on
begin;
do $$
declare
    ticket uuid;
    generation uuid;
    generation_number bigint;
    next_sequence bigint;
    projection jsonb := '{"status":"SUPPORTED","sources":[{"title":"配送帮助","updatedAt":"2026-09-01T00:00:00Z"}]}';
begin
    if not valid_customer_knowledge_projection(projection) then raise exception 'safe metadata rejected'; end if;
    if valid_customer_knowledge_projection('{"status":"SUPPORTED","sources":[{"title":"配送帮助","updatedAt":"2026-09-01T00:00:00Z","chunkId":"private"}]}') then
        raise exception 'private source field accepted';
    end if;
    select t.id,g.id,g.generation_number into ticket,generation,generation_number
    from support_ticket t join agent_processing_generation g on g.ticket_id=t.id
    where t.handling_mode='AGENT' and not t.customer_human_preference and g.status in ('ACTIVE','COMPLETED')
      and g.generation_number=(select max(x.generation_number) from agent_processing_generation x where x.ticket_id=t.id)
    order by t.created_at desc limit 1;
    if ticket is null then raise exception 'prepare a synthetic AGENT ticket before this focused test'; end if;

    select coalesce(max(sequence),0)+1 into next_sequence from customer_public_event where ticket_id=ticket and epoch='public-conversation-v2';
    insert into customer_public_event(ticket_id,epoch,sequence,agent_generation,event_type,payload,occurred_at)
    values (ticket,'public-conversation-v2',next_sequence,generation_number,'PUBLIC_MESSAGE_APPENDED',
        jsonb_build_object('author','AGENT','body','测试回复','sentAt','2026-09-01T00:00:00Z','knowledge',projection),now()),
        (ticket,'public-conversation-v2',next_sequence+1,generation_number,'PUBLIC_MESSAGE_APPENDED',
        jsonb_build_object('author','SUPPORT','body','旧格式回复','sentAt','2026-09-01T00:00:00Z'),now());
    begin
        insert into customer_public_event(ticket_id,epoch,sequence,agent_generation,event_type,payload,occurred_at)
        values (ticket,'public-conversation-v2',next_sequence+2,generation_number,'PUBLIC_MESSAGE_APPENDED',
            jsonb_build_object('author','CUSTOMER','body','不能自造来源','sentAt','2026-09-01T00:00:00Z','knowledge',projection),now());
        raise exception using errcode='ZX169', message='customer supplied knowledge was accepted';
    exception when raise_exception then null;
    end;
    insert into agent_public_reply_stream(generation_id,ticket_id,status,body,updated_at)
    values (generation,ticket,'COMPLETED',repeat('测',2502),now())
    on conflict(generation_id) do update set body=excluded.body,status='COMPLETED';
    begin
        update agent_public_reply_stream set body=repeat('测',2503) where generation_id=generation;
        raise exception using errcode='ZX169', message='oversized reply was accepted';
    exception when check_violation then null;
    end;
end;
$$;
rollback;
