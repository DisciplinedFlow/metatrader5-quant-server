<script setup>
</script>

<template>
  <nav class="container-fluid">
    <ul>
      <li><strong>MT5 Dashboard</strong></li>
    </ul>
    <ul>
      <li><RouterLink to="/dashboard">Overview</RouterLink></li>
      <li><RouterLink to="/positions">Positions</RouterLink></li>
      <li><RouterLink to="/order">Order</RouterLink></li>
      <li><RouterLink to="/history">History</RouterLink></li>
      <li><RouterLink to="/chart">Chart</RouterLink></li>
      <li><RouterLink to="/logs">Logs</RouterLink></li>
      <li><RouterLink to="/strategies">Strategies</RouterLink></li>
    </ul>
  </nav>
</template>
