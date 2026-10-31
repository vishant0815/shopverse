"use client";

import { Field } from "./ui";

export const emptyAddress = {
  full_name: "", phone: "", line1: "", line2: "", city: "", county: "", postcode: "", country: "GB",
};

export default function AddressForm({ value, onChange, errors = {} }) {
  const set = (key) => (event) => onChange({ ...value, [key]: event.target.value });
  const field = (key, label, props = {}) => (
    <Field label={label} name={key} value={value[key]} onChange={set(key)} error={errors[key]} {...props} />
  );

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {field("full_name", "Full name", { autoComplete: "name", required: true })}
      {field("phone", "Phone", { type: "tel", autoComplete: "tel", required: true })}
      {field("line1", "Address line 1", { autoComplete: "address-line1", required: true, className: "sm:col-span-2" })}
      {field("line2", "Address line 2 (optional)", { autoComplete: "address-line2", className: "sm:col-span-2" })}
      {field("city", "Town or city", { autoComplete: "address-level2", required: true })}
      {field("county", "County (optional)", { autoComplete: "address-level1" })}
      {field("postcode", "Postcode", { autoComplete: "postal-code", required: true })}
      {field("country", "Country code", { autoComplete: "country", maxLength: 2, hint: "Two letters, e.g. GB", required: true })}
    </div>
  );
}
