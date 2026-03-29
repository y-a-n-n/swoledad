async function putJson(url, payload) {
  const response = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Request failed");
  }
  return data;
}

document.getElementById("inventory-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const weightInputs = Array.from(form.querySelectorAll('input[name="weight_kg"]'));
  const countInputs = Array.from(form.querySelectorAll('input[name="plate_count"]'));
  const payload = {
    barbell_weight_kg: Number(form.elements.barbell_weight_kg.value),
    plate_inventory: weightInputs.map((input, index) => ({
      weight_kg: Number(input.value),
      plate_count: Number(countInputs[index].value),
    })),
  };
  await putJson("/api/config/inventory", payload);
  window.location.reload();
});

document.getElementById("big3-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form).entries());
  await putJson("/api/config/big3", payload);
  window.location.reload();
});
