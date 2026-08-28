"use client";
import { useState } from "react";

let idCounter = 0;

export function DropdownAggregate({
    title,
    options,
    setterCallback,
    removeNegate,
    removeRemove
}: {
    title: string,
    options: string[],
    setterCallback: (value: string[]) => void,
    removeNegate?: boolean,
    removeRemove?: boolean
}) {
    const [rows, setRows] = useState<{ id: number; value: string }[]>([
        { id: idCounter++, value: "" }
    ]);

    const emit = (updatedRows: { id: number; value: string }[]) => {
        setterCallback(updatedRows.map(r => r.value).filter(v => v !== ""));
    };

    const handleRowChange = (id: number, value: string) => {
        let newRows = rows.map(row => (row.id === id ? { ...row, value } : row));

        if (value === "" && newRows.length > 1) {
            newRows = newRows.filter(row => row.id !== id);
        }

        setRows(newRows);
        emit(newRows);
    };

    const lastRow = rows[rows.length - 1];

    const addRow = () => setRows([...rows, { id: idCounter++, value: "" }])

    return (
        <div className="search-col">
            {rows.map(row => (
                <Dropdown
                    key={row.id}
                    title={title}
                    options={options.filter(option => rows.every(r => r.id === row.id || r.value !== option))}
                    value={row.value}
                    setterCallback={(value: string) => handleRowChange(row.id, value)}
                    removeNegate={removeNegate}
                    removeRemove={removeRemove}
                    addRow={(row == lastRow) && lastRow.value !== "" ? addRow : undefined}
                />
            ))}
        </div>
    );
}

export function Dropdown({
    title,
    options,
    value,
    setterCallback,
    removeNegate,
    removeRemove,
    addRow
}: {
    title: string,
    options: string[],
    value: string,
    setterCallback: (value: any) => void,
    removeNegate?: boolean,
    removeRemove?: boolean,
    addRow?: () => void
}) {
    const [open, setOpen] = useState(false);

    const negate = value && value.startsWith("!");
    const selected = negate ? value.slice(1) : value;
    const [ label, setLabel ] = useState(selected || title);

    return (
        <div className="dropdown-header">
            {!removeNegate && (
                <button
                    type="button"
                    className={`text ${negate ? 'button-not-rev' : 'button-not'} img-btn`}
                    onClick={() => {
                        if (!selected) return; // nothing to negate yet
                        setterCallback(negate ? selected : '!' + selected);
                    }}
                >
                    ¬
                </button>
            )}
            <div className="dropdown text" onClick={() => setOpen(!open)}>
                <div className="dropdown-header">
                    <button className="text" type="button">{label}</button>
                    <button
                        className={`text ${open ? 'button-img-rev' : 'button-img'}`}
                        type="button"
                        onClick={(e) => {
                            e.stopPropagation();
                            setOpen(!open);
                        }}
                    >
                        <img className="img-btn" src={open ? "up.svg" : "down.svg"} />
                    </button>
                </div>
                {open && (
                    <div className="dropdown-content">
                        {options.map(option => (
                            <button
                                type="button"
                                key={option}
                                onClick={() => {
                                    setterCallback(negate ? '!' + option : option);
                                    setOpen(false);
                                    setLabel(option);
                                }}
                                className={option === selected ? 'button-not-rev' : ''}
                            >
                                {option}
                            </button>
                        ))}
                    </div>
                )}
            </div>
            {label !== title && !removeRemove && (
                <button
                    type="button"
                    className="text button-not img-btn"
                    onClick={() => {
                        setterCallback('');
                        setLabel(title);
                    }}
                >
                    ×
                </button>
            )}
            {addRow && 
                <button
                    type="button"
                    className="text button-not img-btn"
                    onClick={addRow}
                >
                    +
                </button>
            }
        </div>
    );
}