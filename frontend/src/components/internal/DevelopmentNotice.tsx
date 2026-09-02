import { useState } from "react";
import { Button, Modal } from "antd";

export function DevelopmentNotice({ label }: { label: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        {label}
      </button>
      <Modal
        title={`${label} · 开发中`}
        open={open}
        onCancel={() => setOpen(false)}
        footer={<Button onClick={() => setOpen(false)}>知道了</Button>}
      >
        <p role="status">此功能尚未开放。本次操作未提交业务请求，也未更改任何业务状态。</p>
      </Modal>
    </>
  );
}
