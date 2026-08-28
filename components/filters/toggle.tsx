export default function Toggle({
    setterCallback, 
    value,
    str1,
    str2
}: {
    setterCallback: (value: boolean) => void, 
    value: boolean
    str1: string,
    str2: string
}) {
    return (
        <div className="text toggle-row" onClick={() => setterCallback(!value)}>
            <button type="button" className={!value ? 'button-img-rev' : undefined}>{str1}</button>
            <button type="button" className={value ? 'button-img-rev' : undefined}>{str2}</button>
        </div>
    );
}