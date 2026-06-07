import React, { useRef, useState, ChangeEvent } from "react";
import { Upload } from "lucide-react";

interface FileSelectorProps {
  onFilesSelected: (files: File[]) => void | Promise<void>;
  accept?: string;
  multiple?: boolean;
  label?: string;
}

export const FileSelector: React.FC<FileSelectorProps> = ({
  onFilesSelected,
  accept = "*",
  multiple = false,
  label,
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedNames, setSelectedNames] = useState<string[]>([]);

  const handleButtonClick = () => {
    // Programmatically open the native browser file dialog
    fileInputRef.current?.click();
  };

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const fileList = event.target.files;
    if (!fileList) return;

    const filesArray = Array.from(fileList);
    
    setSelectedNames(filesArray.map((file) => file.name));
    onFilesSelected(filesArray);
    event.target.value = "";
  };

  return (
    <div className="flex flex-col items-start gap-2">
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileChange}
        accept={accept}
        multiple={multiple}
        className="hidden"
      />

      <button
        type="button"
        onClick={handleButtonClick}
        className="inline-flex items-center gap-2 rounded bg-gray-900 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-gray-800"
      >
        <Upload className="h-4 w-4" />
        {label ?? (multiple ? "Upload agents" : "Upload agent")}
      </button>

      {selectedNames.length > 0 && (
        <ul className="m-0 list-disc pl-5 text-xs text-gray-500">
          {selectedNames.map((name, index) => (
            <li key={index}>{name}</li>
          ))}
        </ul>
      )}
    </div>
  );
};
