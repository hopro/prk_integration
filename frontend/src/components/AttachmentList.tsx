import Button from '@mui/material/Button';
import Divider from '@mui/material/Divider';
import AddIcon from '@mui/icons-material/Add';
import AttachmentForm from './AttachmentForm';
import type { AttachmentData } from '../types';

interface Props {
  attachments: AttachmentData[];
  onChange: (v: AttachmentData[]) => void;
  defaultMo: number;
  spmoMap: Record<number, string>;
}

export default function AttachmentList({ attachments, onChange, defaultMo, spmoMap }: Props) {
  const emptyAttachment: AttachmentData = {
    typeprk: 1,
    mo: defaultMo,
    podr: '',
    dbeg: '',
    meth: 2,
  };

  const handleChange = (index: number, value: AttachmentData) => {
    const updated = attachments.map((a, i) => (i === index ? value : a));
    onChange(updated);
  };

  const handleRemove = (index: number) => {
    onChange(attachments.filter((_, i) => i !== index));
  };

  const handleAdd = () => {
    onChange([...attachments, { ...emptyAttachment }]);
  };

  return (
    <>
      {attachments.map((attachment, index) => (
        <div key={index}>
          {index > 0 && <Divider sx={{ my: 2 }} />}
          <AttachmentForm
            attachment={attachment}
            index={index}
            onChange={handleChange}
            onRemove={handleRemove}
            canRemove={attachments.length > 1}
            spmoMap={spmoMap}
          />
        </div>
      ))}
      <Button
        startIcon={<AddIcon />}
        onClick={handleAdd}
        variant="outlined"
        sx={{ mt: 2 }}
      >
        Добавить прикрепление
      </Button>
    </>
  );
}
