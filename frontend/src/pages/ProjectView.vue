<template>
  <v-container>
    <!-- Breadcrumb -->
    <div class="mb-4">
      <v-btn
        variant="text"
        size="small"
        prepend-icon="mdi-arrow-left"
        to="/"
        color="secondary"
        class="pl-0"
      >
        Projects
      </v-btn>
    </div>

    <!-- Title row — single horizontal line, all items share one baseline -->
    <div v-if="loading || project" class="d-flex align-center mb-6 gap-3">
      <!-- Title -->
      <h1 class="text-h4 font-weight-bold text-truncate">
        {{ project?.display_name || humanize(name) }}
      </h1>

      <!-- Run number -->
      <v-chip
        v-if="runNumber(name)"
        size="small"
        color="secondary"
        variant="tonal"
        class="font-weight-bold flex-shrink-0"
      >
        #{{ runNumber(name) }}
      </v-chip>

      <!-- Scenario count -->
      <v-chip
        v-if="project?.scenario_count"
        size="small"
        color="primary"
        variant="tonal"
        class="flex-shrink-0"
      >
        {{ project.scenario_count }} Scenario{{ project.scenario_count !== 1 ? 's' : '' }}
      </v-chip>

      <!-- Date — subtle, middle of the row -->
      <span class="text-body-2 text-medium-emphasis flex-shrink-0">
        <v-icon size="x-small" class="mr-1">mdi-calendar-clock</v-icon>
        {{ formatDate(project?.created_at) }}
      </span>

      <v-spacer />

      <!-- Delete Project -->
      <v-btn
        color="error"
        variant="text"
        prepend-icon="mdi-delete-outline"
        @click="deleteDialog = true"
      >
        Delete
      </v-btn>

    </div>


    <v-row v-if="loading">
      <v-col cols="12" class="text-center">
        <v-progress-circular indeterminate />
      </v-col>
    </v-row>

    <template v-else-if="!project">
      <v-row class="mt-12">
        <v-col class="text-center">
          <v-icon size="64" color="error" class="mb-4">mdi-alert-circle-outline</v-icon>
          <h2 class="text-h5 mb-2">Project Not Found</h2>
          <p class="text-medium-emphasis mb-6">The project "{{ name }}" could not be loaded or no longer exists.</p>
          <v-btn color="primary" to="/" variant="tonal">Return to Dashboard</v-btn>
        </v-col>
      </v-row>
    </template>

    <template v-else>
      <div class="mb-6">
        <v-tabs v-model="activeTab" color="primary" grow>
          <v-tab value="results">
            <v-icon start>mdi-chart-bar</v-icon>
            Results
          </v-tab>
          <v-tab value="diagram">
            <v-icon start>mdi-graph-outline</v-icon>
            Diagram
          </v-tab>
          <v-tab value="analytics">
            <v-icon start>mdi-magnify-expand</v-icon>
            Analytics
          </v-tab>
          <v-tab value="reports">
            <v-icon start>mdi-text-box-outline</v-icon>
            Summary
          </v-tab>
          <v-tab value="params">
            <v-icon start>mdi-tune-variant</v-icon>
            Baseline Parameters
          </v-tab>
          <v-tab value="scenarios">
            <v-icon start>mdi-test-tube</v-icon>
            Scenarios
          </v-tab>
        </v-tabs>
      </div>

      <v-window v-model="activeTab">
        <!-- DIAGRAM TAB -->
        <v-window-item value="diagram" eager>
          <v-card border variant="flat" rounded="lg">
            <!-- Header: title + scenario buttons -->
            <v-card-item class="pb-2">
              <v-card-title class="text-subtitle-1">Process Diagram</v-card-title>
              <template v-slot:append>
                <div class="d-flex align-center" style="gap: 12px">
                  <!-- Legend: only in ANALYZE mode -->
                  <Transition name="fade">
                    <div v-if="diagramScenario" class="d-flex align-center" style="gap: 6px">
                      <div style="width:10px;height:10px;border-radius:2px;background:rgb(var(--v-theme-primary))" />
                      <span class="text-caption text-medium-emphasis">Avg. wait time</span>
                    </div>
                  </Transition>
                  <!-- Scenario toggle: click to enter ANALYZE, click again to deselect -->
                  <v-btn-toggle
                    v-if="analyticsScenarios.length"
                    v-model="diagramScenario"
                    color="primary"
                    variant="outlined"
                    density="compact"
                  >
                    <v-btn
                      v-for="sc in analyticsScenarios"
                      :key="sc.scenario"
                      :value="sc.scenario"
                      size="small"
                    >{{ sc.scenario.replace(/_/g, ' ') }}</v-btn>
                  </v-btn-toggle>
                  <span v-else-if="!analyticsLoading" class="text-caption text-disabled">No scenarios yet</span>
                </div>
              </template>
            </v-card-item>
            <v-divider />
            <v-card-text class="pa-0" style="height: 600px; position: relative">
              <div v-if="bpmnXmlLoading || analyticsLoading" class="d-flex align-center justify-center" style="height:100%">
                <v-progress-circular indeterminate color="primary" />
              </div>
              <div v-else-if="bpmnXmlError" class="d-flex align-center justify-center" style="height:100%">
                <v-alert type="warning" variant="tonal">{{ bpmnXmlError }}</v-alert>
              </div>
              <AureaEdenBpmnDiagram
                v-else-if="bpmnXml"
                :bpmn-xml="bpmnXml"
                :mode="diagramScenario ? 'ANALYZE' : 'VIEW'"
                :values="diagramValues"
                :theme="isDark ? 'DARK' : 'LIGHT'"
                style="width:100%;height:100%"
              />
            </v-card-text>
          </v-card>
        </v-window-item>

        <!-- RESULTS TAB -->
        <v-window-item value="results">
          <v-alert
            v-if="project?.results_stale"
            type="warning"
            variant="tonal"
            class="mb-4"
            icon="mdi-alert-clock-outline"
          >
            Baseline parameters have changed. These results and reports were produced from an earlier baseline and must be regenerated.
          </v-alert>

          <!-- KPI Table -->
          <v-row v-if="project?.kpis?.length">
            <v-col>
              <v-card border variant="flat">
                <v-card-item>
                  <v-card-title>Simulation KPIs</v-card-title>
                </v-card-item>
                <v-card-text>
                  <v-data-table
                    :headers="kpiHeaders"
                    :items="humanizedKpis"
                    density="comfortable"
                    items-per-page="-1"
                    hide-default-footer
                    class="rounded-lg"
                  />
                </v-card-text>
              </v-card>
            </v-col>
          </v-row>

          <!-- Chart -->
          <v-row v-if="project?.has_chart" class="mt-4">
            <v-col>
              <v-card border variant="flat">
                <v-card-item>
                  <v-card-title>Scenario Comparison</v-card-title>
                </v-card-item>
                <v-card-text class="pa-0">
                  <v-img
                    :src="`${baseUrl}api/projects/${name}/chart`"
                    max-height="600"
                    cover
                    class="bg-grey-lighten-4"
                  />
                </v-card-text>
              </v-card>
            </v-col>
          </v-row>
          <!-- Resource Wait Times -->
          <v-row v-if="waitTimeKeys.length" class="mt-4">
            <v-col>
              <v-card border variant="flat">
                <v-card-item>
                  <v-card-title>Resource Wait Times (hrs)</v-card-title>
                  <v-card-subtitle>Average waiting time per role per scenario</v-card-subtitle>
                </v-card-item>
                <v-card-text>
                  <v-data-table
                    :headers="waitTimeHeaders"
                    :items="waitTimeRows"
                    density="comfortable"
                    items-per-page="-1"
                    hide-default-footer
                    class="rounded-lg"
                  />
                </v-card-text>
              </v-card>
            </v-col>
          </v-row>
        </v-window-item>

        <!-- ANALYTICS TAB -->
        <v-window-item value="analytics">
          <AnalyticsTab :project-name="name" />
        </v-window-item>

        <!-- BASELINE PARAMETERS TAB -->
        <v-window-item value="params">
          <div class="mb-4">
            <h2 class="text-h5 font-weight-medium">Baseline Parameters</h2>
            <p class="text-body-2 text-medium-emphasis mb-0">
              These are the active values used when the simulation runs. Update a value when you have better local knowledge and record why it is more appropriate.
            </p>
          </div>
          <v-alert type="info" variant="tonal" density="comfortable" class="mb-4" icon="mdi-information-outline">
            <strong>How to read this page.</strong> Values marked <em>Generated estimate</em> come from the original baseline generation.
            A pencil lets you replace one value and preserve an audit record. {{ parameterEvidenceSummary }}
          </v-alert>
          <v-alert
            v-if="project?.results_stale"
            type="warning"
            variant="tonal"
            class="mb-4"
            icon="mdi-alert-clock-outline"
          >
            The baseline has been edited. Existing simulation results remain visible for reference but are stale until the simulation is rerun.
          </v-alert>

          <!-- 1. Arrival Rate -->
          <v-row>
            <v-col>
              <v-card border variant="flat">
                <v-card-item>
                  <v-card-title>Arrival Rate</v-card-title>
                  <v-card-subtitle>Case inter-arrival distribution and working calendar</v-card-subtitle>
                  <template #append>
                    <v-btn icon="mdi-pencil-outline" variant="text" size="small" aria-label="Edit arrival rate" @click="openArrivalEdit" />
                  </template>
                </v-card-item>
                <v-card-text class="pb-4">
                  <template v-if="project?.base_params?.arrival_time_distribution?.frequency?.events">
                    <!-- New format: AI-determined frequency with rationale -->
                    <div class="d-flex mb-3" style="gap:2rem">
                      <div>
                        <div class="text-caption text-medium-emphasis text-uppercase mb-1" style="letter-spacing:.08em">Frequency</div>
                        <div class="text-h6 font-weight-bold">
                          {{ project.base_params.arrival_time_distribution.frequency.events }}
                          {{ project.base_params.arrival_time_distribution.frequency.events === 1 ? 'case' : 'cases' }}
                          per
                          {{ project.base_params.arrival_time_distribution.frequency.per_count > 1 ? project.base_params.arrival_time_distribution.frequency.per_count + ' ' : '' }}{{ project.base_params.arrival_time_distribution.frequency.per_unit }}
                        </div>
                      </div>
                      <div>
                        <div class="text-caption text-medium-emphasis text-uppercase mb-1" style="letter-spacing:.08em">Distribution</div>
                        <div class="text-h6 font-weight-bold">{{ formatDistribution(project?.base_params?.arrival_time_distribution?.distribution_name) }}</div>
                      </div>
                      <div v-if="project?.base_params?.arrival_time_calendar?.length">
                        <div class="text-caption text-medium-emphasis text-uppercase mb-1" style="letter-spacing:.08em">Calendar</div>
                        <div class="text-body-1 font-weight-bold" v-for="(p, i) in project.base_params.arrival_time_calendar" :key="i">{{ formatTimePeriod(p) }}</div>
                      </div>
                    </div>
                    <v-divider class="mb-3" />
                    <p class="text-body-2 text-medium-emphasis">
                      <v-icon size="x-small" class="mr-1">mdi-information-outline</v-icon>
                      {{ project.base_params.arrival_time_distribution.frequency.rationale }}
                    </p>
                  </template>
                  <template v-else>
                    <!-- Legacy format: raw seconds only -->
                    <div class="d-flex" style="gap:2rem">
                      <div>
                        <div class="text-caption text-medium-emphasis text-uppercase mb-1" style="letter-spacing:.08em">Mean Interval</div>
                        <div class="text-h6 font-weight-bold">{{ arrivalRateMean }}</div>
                      </div>
                      <div>
                        <div class="text-caption text-medium-emphasis text-uppercase mb-1" style="letter-spacing:.08em">Distribution</div>
                        <div class="text-h6 font-weight-bold">{{ formatDistribution(project?.base_params?.arrival_time_distribution?.distribution_name) }}</div>
                      </div>
                      <div v-if="project?.base_params?.arrival_time_calendar?.length">
                        <div class="text-caption text-medium-emphasis text-uppercase mb-1" style="letter-spacing:.08em">Calendar</div>
                        <div class="text-body-1 font-weight-bold" v-for="(p, i) in project.base_params.arrival_time_calendar" :key="i">{{ formatTimePeriod(p) }}</div>
                      </div>
                    </div>
                  </template>
                </v-card-text>
              </v-card>
            </v-col>
          </v-row>

          <!-- 2. Gateway Branching -->
          <v-row class="mt-4" v-if="project?.base_params?.gateway_branching_probabilities?.length">
            <v-col>
              <v-card border variant="flat">
                <v-card-item>
                  <v-card-title>Gateway Branching Probabilities</v-card-title>
                  <v-card-subtitle>Path likelihoods used by the baseline</v-card-subtitle>
                </v-card-item>
                <v-card-text>
                  <v-row>
                    <v-col cols="12" md="6" v-for="gw in project.base_params.gateway_branching_probabilities" :key="gw.gateway_id">
                      <div class="d-flex align-center mb-2">
                        <div class="text-caption font-weight-bold text-medium-emphasis text-uppercase">{{ humanizeGateway(gw.gateway_id) }}</div>
                        <v-spacer />
                        <v-btn icon="mdi-pencil-outline" variant="text" size="x-small" aria-label="Edit gateway probabilities" @click="openGatewayEdit(gw)" />
                      </div>
                      <v-table density="compact">
                        <tbody>
                          <tr v-for="(prob, i) in gw.probabilities" :key="prob.path_id">
                            <td style="width:80px">Path {{ String.fromCharCode(65 + Number(i)) }}</td>
                            <td><v-progress-linear :model-value="prob.value * 100" color="primary" height="6" rounded /></td>
                            <td class="text-right font-weight-bold" style="width:48px">{{ Math.round(prob.value * 100) }}%</td>
                          </tr>
                        </tbody>
                      </v-table>
                    </v-col>
                  </v-row>
                </v-card-text>
              </v-card>
            </v-col>
          </v-row>

          <!-- 3. Resource Profiles + 4. Resource Calendars (side by side) -->
          <v-row class="mt-4">
            <v-col cols="12" md="6">
              <v-card border variant="flat">
                <v-card-item>
                  <v-card-title>Resource Profiles</v-card-title>
                  <v-card-subtitle>Costs and headcounts used by the baseline</v-card-subtitle>
                </v-card-item>
                <v-card-text>
                  <v-table density="compact">
                    <thead>
                      <tr><th>Role</th><th>Cost/hr</th><th>Headcount</th><th class="text-right">Edit</th></tr>
                    </thead>
                    <tbody>
                      <tr v-for="res in project?.base_params?.resource_profiles" :key="res.id">
                        <td class="font-weight-medium">{{ res.name }}</td>
                        <td>${{ res.resource_list[0]?.cost_per_hour?.toFixed(2) }}</td>
                        <td>{{ res.resource_list.reduce((sum: number, r: any) => sum + Number(r.amount ?? 1), 0) }}</td>
                        <td class="text-right">
                          <v-btn icon="mdi-pencil-outline" variant="text" size="small" :aria-label="`Edit ${res.name}`" @click="openResourceEdit(res)" />
                        </td>
                      </tr>
                    </tbody>
                  </v-table>
                </v-card-text>
              </v-card>
            </v-col>

            <v-col cols="12" md="6">
              <v-card border variant="flat">
                <v-card-item>
                  <v-card-title>Resource Calendars</v-card-title>
                  <v-card-subtitle>Working hours per resource pool</v-card-subtitle>
                </v-card-item>
                <v-card-text>
                  <v-table density="compact">
                    <thead><tr><th>Calendar</th><th>Schedule</th></tr></thead>
                    <tbody>
                      <tr v-for="cal in project?.base_params?.resource_calendars" :key="cal.id">
                        <td class="font-weight-medium">{{ cal.name || humanize(cal.id) }}</td>
                        <td>
                          <v-chip v-for="(p, i) in cal.time_periods" :key="i" size="small" variant="outlined" class="mr-1">{{ formatTimePeriod(p) }}</v-chip>
                        </td>
                      </tr>
                    </tbody>
                  </v-table>
                </v-card-text>
              </v-card>
            </v-col>
          </v-row>

          <!-- 5. Task Durations -->
          <v-row class="mt-4">
            <v-col>
              <v-card border variant="flat">
                <v-card-item>
                  <v-card-title>Task Durations</v-card-title>
                  <v-card-subtitle>Processing-time estimates used by the baseline</v-card-subtitle>
                </v-card-item>
                <v-card-text>
                  <v-table density="compact">
                    <thead>
                      <tr><th>Task</th><th>Distribution</th><th>Mean (min)</th><th>Evidence</th><th class="text-right">Edit</th></tr>
                    </thead>
                    <tbody>
                      <tr v-for="dist in project?.base_params?.task_resource_distribution" :key="dist.task_id">
                        <td class="font-weight-medium">{{ humanize(dist.task_id) }}</td>
                        <td><v-chip size="x-small" variant="tonal">{{ formatDistribution(dist.resources[0]?.distribution_name) }}</v-chip></td>
                        <td>{{ ((dist.resources[0]?.distribution_params?.[0]?.value ?? 0) / 60).toFixed(1) }}</td>
                        <td>
                          <v-chip size="x-small" :color="parameterEvidenceLabel(dist) === 'Generated estimate' ? undefined : 'success'" variant="tonal">
                            {{ parameterEvidenceLabel(dist) }}
                          </v-chip>
                          <div v-if="operationalReferenceFor(dist)" class="text-caption text-success mt-1">
                            Measured error {{ operationalErrorFor(dist) }} · operational holdout, n={{ operationalReferenceFor(dist).n }}
                          </div>
                          <div v-else class="text-caption text-medium-emphasis mt-1">Fidelity not assessed for this task</div>
                        </td>
                        <td class="text-right">
                          <v-tooltip location="top" open-delay="300">
                            <template #activator="{ props: tooltipProps }">
                              <v-btn
                                v-bind="tooltipProps"
                                icon="mdi-pencil-outline"
                                variant="text"
                                size="small"
                                :aria-label="`Edit ${humanize(dist.task_id)} duration`"
                                @click="openTaskDurationEdit(dist)"
                              />
                            </template>
                            Manually edit the executable baseline duration. Existing simulation results will become stale.
                          </v-tooltip>
                        </td>
                      </tr>
                    </tbody>
                  </v-table>
                </v-card-text>
              </v-card>
            </v-col>
          </v-row>

        </v-window-item>
        <v-window-item value="scenarios">
          <v-row v-if="!project?.exp_params?.scenarios?.length">
            <v-col>
              <v-alert type="info" variant="tonal">No experiment scenarios found for this project.</v-alert>
            </v-col>
          </v-row>

          <template v-else>
            <v-row>
              <v-col
                cols="12" sm="6" md="4" lg="3" xl="2"
                v-for="(scenario, idx) in project.exp_params.scenarios"
                :key="scenario.name"
              >
                <v-card border variant="flat" class="h-100">
                  <v-card-item>
                    <template v-slot:prepend>
                      <v-avatar color="primary" variant="tonal" size="36" class="text-caption font-weight-bold">
                        {{ String.fromCharCode(65 + Number(idx)) }}
                      </v-avatar>
                    </template>
                    <v-card-title>{{ humanize(scenario.name) }}</v-card-title>
                    <v-card-subtitle v-if="scenario.arrival_rate">
                      Every {{ formatInterval(scenario.arrival_rate) }}
                    </v-card-subtitle>
                  </v-card-item>
                  <!-- Change summary chips — always reserve space for vertical alignment -->
                  <div class="px-4 pb-1 d-flex flex-wrap gap-1" style="min-height: 28px">
                    <!-- Demand chip -->
                    <v-chip
                      v-if="Number(idx) > 0 && Number(scenario.arrival_rate) !== Number(project.exp_params.scenarios[0].arrival_rate)"
                      size="x-small"
                      :color="Number(scenario.arrival_rate) < Number(project.exp_params.scenarios[0].arrival_rate) ? 'warning' : 'secondary'"
                      variant="flat"
                    >
                      {{
                        Number(scenario.arrival_rate) < Number(project.exp_params.scenarios[0].arrival_rate)
                          ? `↑ ~${Math.round(Number(project.exp_params.scenarios[0].arrival_rate) / Number(scenario.arrival_rate))}× more frequent`
                          : `↓ ~${Math.round(Number(scenario.arrival_rate) / Number(project.exp_params.scenarios[0].arrival_rate))}× less frequent`
                      }}
                    </v-chip>
                    <!-- Staffing chip -->
                    <v-chip
                      v-if="Number(idx) > 0 && staffingChipLabel(scenario, Number(idx))"
                      size="x-small"
                      :color="resourceDiffs(scenario, Number(idx)).every((d: any) => Number(d.new) > Number(d.baseline)) ? 'primary' : resourceDiffs(scenario, Number(idx)).every((d: any) => Number(d.new) < Number(d.baseline)) ? 'warning' : 'secondary'"
                      variant="flat"
                    >
                      {{ staffingChipLabel(scenario, Number(idx)) }}
                    </v-chip>
                    <!-- Cost chip -->
                    <v-chip
                      v-if="Number(idx) > 0 && costDiffs(scenario, Number(idx)).length > 0"
                      size="x-small"
                      color="secondary"
                      variant="flat"
                    >
                      $ Costs revised
                    </v-chip>
                  </div>
                  <v-card-text class="pt-2">
                    <!-- Description (from AI or fallback) -->
                    <p class="text-body-2 mb-4 font-italic text-medium-emphasis" style="min-height: 5.5em">
                      {{ scenario.description || scenarioFallbackDescription(scenario, Number(idx)) }}
                    </p>

                    <!-- Baseline staffing (idx 0) / Staffing diffs (idx > 0) -->
                    <template v-if="idx === 0">
                      <div class="text-caption text-medium-emphasis font-weight-bold mb-2 text-uppercase">Baseline Staffing</div>
                      <div class="mb-3">
                        <div
                          v-for="res in project?.base_params?.resource_profiles"
                          :key="res.id"
                          class="d-flex align-center justify-space-between py-1"
                          style="border-bottom: 1px solid rgba(128,128,128,0.15)"
                        >
                          <span class="text-body-2">{{ humanize(res.name) }}</span>
                          <span class="font-weight-bold">
                            {{ res.resource_list.reduce((sum: number, r: any) => sum + Number(r.amount ?? 1), 0) }}
                          </span>
                        </div>
                      </div>
                    </template>
                    <template v-else-if="resourceDiffs(scenario, Number(idx)).length > 0">
                      <div class="text-caption text-medium-emphasis font-weight-bold mb-2 text-uppercase">Staffing Changes vs Baseline</div>
                      <div class="mb-3">
                        <div
                          v-for="diff in resourceDiffs(scenario, Number(idx))"
                          :key="diff.role"
                          class="d-flex align-center justify-space-between py-1"
                          style="border-bottom: 1px solid rgba(128,128,128,0.15)"
                        >
                          <span class="text-body-2">{{ humanize(diff.role) }}</span>
                          <span class="text-body-2 ml-4 flex-shrink-0">
                            <span class="text-medium-emphasis">{{ diff.baseline }}</span>
                            <span class="mx-1 text-medium-emphasis">→</span>
                            <span class="font-weight-bold" :class="Number(diff.new) > Number(diff.baseline) ? 'text-success' : 'text-error'">{{ diff.new }}</span>
                          </span>
                        </div>
                      </div>
                    </template>

                    <!-- Baseline costs (idx 0) / Cost diffs (idx > 0) -->
                    <template v-if="idx === 0">
                      <div class="text-caption text-medium-emphasis font-weight-bold mb-2 text-uppercase mt-3">Baseline Costs</div>
                      <div>
                        <div
                          v-for="(cost, role) in scenario.cost_overrides"
                          :key="String(role)"
                          class="d-flex align-center justify-space-between py-1"
                          style="border-bottom: 1px solid rgba(128,128,128,0.15)"
                        >
                          <span class="text-body-2">{{ humanize(String(role)) }}</span>
                          <span class="font-weight-bold">${{ Number(cost).toFixed(2) }}/hr</span>
                        </div>
                      </div>
                    </template>
                    <template v-else-if="costDiffs(scenario, Number(idx)).length > 0">
                      <div class="text-caption text-medium-emphasis font-weight-bold mb-1 text-uppercase">Cost Changes vs Baseline</div>
                      <div>
                        <div
                          v-for="diff in costDiffs(scenario, Number(idx))"
                          :key="diff.role"
                          class="d-flex align-center justify-space-between py-1"
                          style="border-bottom: 1px solid rgba(128,128,128,0.15)"
                        >
                          <span class="text-body-2">{{ humanize(diff.role) }}</span>
                          <span class="font-weight-bold">${{ diff.new }}/hr</span>
                        </div>
                      </div>
                    </template>
                  </v-card-text>
                </v-card>
              </v-col>
            </v-row>

          </template>
        </v-window-item>

        <!-- REPORT TAB -->
        <v-window-item value="reports">
          <div class="d-flex align-center mb-4">
            <div>
              <h2 class="text-h5 font-weight-medium">Executive Summary</h2>
              <p class="text-body-2 text-medium-emphasis mb-0">
                Review the conclusions online or download the complete report.
              </p>
            </div>
            <v-spacer />
            <v-menu v-if="hasReportFiles" location="bottom end">
              <template v-slot:activator="{ props: menuProps }">
                <v-btn
                  v-bind="menuProps"
                  color="primary"
                  variant="tonal"
                  prepend-icon="mdi-download"
                  append-icon="mdi-chevron-down"
                  class="flex-shrink-0"
                >
                  Download Report
                </v-btn>
              </template>
              <v-list density="compact" min-width="160">
                <v-list-item
                  v-if="reportFileByExt('docx')"
                  prepend-icon="mdi-file-word"
                  title="DOCX"
                  :href="`${baseUrl}api/projects/${name}/download/${reportFileByExt('docx')}`"
                />
                <v-list-item
                  v-if="reportFileByExt('pdf')"
                  prepend-icon="mdi-file-pdf-box"
                  title="PDF"
                  :href="`${baseUrl}api/projects/${name}/download/${reportFileByExt('pdf')}`"
                />
                <v-list-item
                  v-if="reportFileByExt('tex')"
                  prepend-icon="mdi-code-braces"
                  title="LaTeX"
                  :href="`${baseUrl}api/projects/${name}/download/${reportFileByExt('tex')}`"
                />
              </v-list>
            </v-menu>
          </div>

          <!-- Loading state -->
          <div v-if="reportLoading" class="d-flex justify-center align-center py-16">
            <v-progress-circular indeterminate color="primary" size="48" />
          </div>

          <!-- No report available -->
          <v-alert
            v-else-if="!reportContent"
            type="info"
            variant="tonal"
            icon="mdi-file-document-outline"
          >
            No report has been generated for this project yet. Run the AureaSim wizard to produce one.
          </v-alert>

          <!-- Report content -->
          <template v-else>
            <!-- Rendered Markdown -->
            <v-card border variant="flat">
              <v-card-text class="pa-8">
                <div
                  class="report-markdown"
                  v-html="renderedReport"
                />
              </v-card-text>
            </v-card>

            <!-- Sources note -->
            <div class="mt-4 d-flex align-center text-body-2 text-medium-emphasis">
              <v-icon size="small" class="mr-2">mdi-bookshelf</v-icon>
              <span>Citations above document the assumptions used to generate this baseline.</span>
            </div>
          </template>
        </v-window-item>
      </v-window>


      <v-dialog v-model="showPreview" fullscreen transition="dialog-bottom-transition">
        <v-card>
          <v-toolbar color="surface" elevation="1">
            <v-btn icon @click="showPreview = false">
              <v-icon>mdi-close</v-icon>
            </v-btn>
            <v-toolbar-title>{{ currentPreviewFile }}</v-toolbar-title>
            <v-spacer />
            <v-btn
              color="primary"
              variant="flat"
              prepend-icon="mdi-download"
              :href="`${baseUrl}api/projects/${name}/download/${currentPreviewFile}`"
            >
              Download
            </v-btn>
          </v-toolbar>
          
          <v-card-text class="pa-0 h-100 bg-grey-darken-4 d-flex justify-center align-center">
            <iframe
              v-if="isPreviewPdf"
              :src="`${baseUrl}api/projects/${name}/download/${currentPreviewFile}`"
              width="100%"
              height="100%"
              style="border: none"
            ></iframe>
            <div v-else-if="isPreviewText" class="pa-10 w-100 h-100 overflow-auto">
              <pre class="text-body-2">{{ previewContent }}</pre>
            </div>
            <v-alert v-else type="info" variant="tonal" icon="mdi-file-question">
              This file format cannot be previewed directly. Please download it to view its content.
            </v-alert>
          </v-card-text>
        </v-card>
      </v-dialog>

      <!-- Baseline parameter editor -->
      <v-dialog v-model="parameterEditDialog" max-width="640">
        <v-card>
          <v-card-item>
            <v-card-title>Edit {{ parameterEditTitle }}</v-card-title>
            <v-card-subtitle>This changes the executable baseline. Existing simulation results will be marked stale until rerun.</v-card-subtitle>
          </v-card-item>
          <v-card-text>
            <template v-if="parameterEditKind === 'arrival'">
              <v-row>
                <v-col cols="12" sm="4">
                  <v-text-field v-model.number="parameterEditValues.events" type="number" min="0.000001" label="Cases" />
                </v-col>
                <v-col cols="12" sm="4">
                  <v-text-field v-model.number="parameterEditValues.per_count" type="number" min="0.000001" label="Per" />
                </v-col>
                <v-col cols="12" sm="4">
                  <v-select v-model="parameterEditValues.per_unit" :items="arrivalUnits" label="Time unit" />
                </v-col>
              </v-row>
            </template>

            <template v-else-if="parameterEditKind === 'resource'">
              <v-text-field v-model.number="parameterEditValues.headcount" type="number" min="1" step="1" label="Headcount" />
              <v-text-field v-model.number="parameterEditValues.cost_per_hour" type="number" min="0" label="Cost per hour" />
              <v-select v-model="parameterEditValues.calendar" :items="calendarOptions" item-title="title" item-value="value" label="Calendar" />
            </template>

            <template v-else-if="parameterEditKind === 'task_duration'">
              <v-text-field v-model.number="parameterEditValues.mean_minutes" type="number" min="0.000001" label="Mean duration (minutes)" />
              <v-text-field v-model.number="parameterEditValues.stddev_minutes" type="number" min="0" label="Standard deviation (minutes)" />
              <v-alert type="info" variant="tonal" density="compact" class="mb-3">
                The current distribution family is retained; this edit changes its mean and standard deviation. Use a local measurement or a documented expert judgment where possible.
              </v-alert>
            </template>

            <template v-else-if="parameterEditKind === 'gateway'">
              <v-text-field
                v-for="path in parameterEditValues.paths"
                :key="path.path_id"
                v-model.number="path.percent"
                type="number"
                min="0"
                max="100"
                :label="`${humanize(path.path_id)} probability (%)`"
              />
              <div class="text-caption text-medium-emphasis mb-3">Probabilities must total 100%.</div>
            </template>

            <v-select
              v-model="parameterEvidenceType"
              :items="parameterEvidenceTypes"
              item-title="title"
              item-value="value"
              label="Basis for this change"
              hint="This is saved with the parameter history. It does not claim that the value has been independently validated."
              persistent-hint
              class="mb-3"
            />
            <v-text-field v-model="parameterReviewerId" label="Recorded by" hint="Name, role, or another traceable identifier." persistent-hint class="mb-3" />
            <v-textarea
              v-model="parameterJustification"
              label="Evidence and reason"
              hint="State the source, measurement period or expert rationale that supports this value."
              persistent-hint
              rows="3"
            />
            <v-alert v-if="parameterEditError" type="error" variant="tonal" density="compact" class="mt-3">
              {{ parameterEditError }}
            </v-alert>
          </v-card-text>
          <v-card-actions>
            <v-spacer />
            <v-btn variant="text" @click="parameterEditDialog = false">Cancel</v-btn>
            <v-btn color="primary" variant="flat" :loading="parameterSaving" @click="saveBaselineParameter">Save baseline value</v-btn>
          </v-card-actions>
        </v-card>
      </v-dialog>

      <v-dialog v-model="deleteDialog" max-width="400">
        <v-card>
          <v-card-title class="text-h6 text-error">
            Delete Project?
          </v-card-title>
          <v-card-text>
            Are you sure you want to delete the project <strong>{{ project?.display_name || humanize(name) }}</strong>? This action cannot be undone.
          </v-card-text>
          <v-card-actions>
            <v-spacer></v-spacer>
            <v-btn variant="text" @click="deleteDialog = false">Cancel</v-btn>
            <v-btn color="error" variant="flat" :loading="deleting" @click="confirmDelete">Delete</v-btn>
          </v-card-actions>
        </v-card>
      </v-dialog>
    </template>
  </v-container>
</template>

<script lang="ts" setup>
  import { ref, computed, onMounted, watch } from 'vue'
  import { useRouter } from 'vue-router'
  import { marked } from 'marked'
  import { useTheme } from 'vuetify'
  import AnalyticsTab from '@/components/AnalyticsTab.vue'
  import AureaEdenBpmnDiagram from 'aurea-eden/vue'

  const baseUrl = import.meta.env.BASE_URL

  const props = defineProps<{
    name: string
  }>()

  interface ProjectDetail {
    name: string
    display_name: string
    created_at: number
    has_kpis: boolean
    has_chart: boolean
    reports: string[]
    scenario_count: number
    results_stale: boolean
    kpis: Record<string, string | number>[]
    base_params: any
    exp_params: any
    ai_summary: string | null
    operational_references: any | null
  }

  const project = ref<ProjectDetail | null>(null)
  const loading = ref(true)
  const theme = useTheme()
  const router = useRouter()
  const isDark = computed(() => theme.global.current.value.dark)

  const activeTab = ref('results')
  const deleteDialog = ref(false)
  const deleting = ref(false)
  const parameterEditDialog = ref(false)
  const parameterEditKind = ref<'arrival' | 'resource' | 'task_duration' | 'gateway'>('task_duration')
  const parameterEditEntityId = ref('')
  const parameterEditTitle = ref('baseline parameter')
  const parameterEditValues = ref<any>({})
  const parameterReviewerId = ref('local-user')
  const parameterEvidenceType = ref('expert_judgment')
  const parameterEvidenceTypes = [
    { title: 'Local measurement or operational data', value: 'local_measurement' },
    { title: 'Expert judgment', value: 'expert_judgment' },
    { title: 'Policy, contractual or regulatory requirement', value: 'policy_requirement' },
    { title: 'Other documented local knowledge', value: 'other' },
  ]
  const parameterJustification = ref('')
  const parameterEditError = ref('')
  const parameterSaving = ref(false)
  const arrivalUnits = ['second', 'minute', 'hour', 'day', 'week', 'month']
  const calendarOptions = computed(() =>
    (project.value?.base_params?.resource_calendars ?? []).map((calendar: any) => ({
      title: calendar.name || humanize(calendar.id),
      value: calendar.id,
    }))
  )
  const operationalReferenceByTask = computed(() => {
    const references = project.value?.operational_references?.references ?? []
    return new Map(references.map((reference: any) => [String(reference.entity_id), reference]))
  })
  const parameterEvidenceSummary = computed(() => {
    const count = operationalReferenceByTask.value.size
    return count
      ? `${count} task durations have a matched independent chronological process-mining reference; their measured error is shown below.`
      : 'This project has no compatible independent reference attached, so fidelity is not assessed here.'
  })

  function beginParameterEdit(
    kind: 'arrival' | 'resource' | 'task_duration' | 'gateway',
    entityId: string,
    title: string,
    values: any,
  ) {
    parameterEditKind.value = kind
    parameterEditEntityId.value = entityId
    parameterEditTitle.value = title
    parameterEditValues.value = values
    parameterEvidenceType.value = 'expert_judgment'
    parameterJustification.value = ''
    parameterEditError.value = ''
    parameterEditDialog.value = true
  }

  function parameterEvidenceLabel(task: any): string {
    const status = task.resources?.[0]?.evidence_status
    if (status === 'local_measurement') return 'Local measurement'
    if (status === 'policy_requirement') return 'Policy requirement'
    if (status === 'other') return 'Documented local knowledge'
    if (status === 'expert_judgment' || status === 'expert_refined') return 'Expert judgment'
    return 'Generated estimate'
  }

  function operationalReferenceFor(task: any): any | null {
    return operationalReferenceByTask.value.get(String(task.task_id)) ?? null
  }

  function operationalErrorFor(task: any): string {
    const reference = operationalReferenceFor(task)
    const estimate = Number(task.resources?.[0]?.distribution_params?.[0]?.value ?? 0)
    const observed = Number(reference?.mean ?? 0)
    if (!reference || !Number.isFinite(estimate) || !Number.isFinite(observed) || observed <= 0) return 'unavailable'
    return `${(Math.abs(estimate - observed) / observed * 100).toFixed(1)}%`
  }

  function openArrivalEdit() {
    const distribution = project.value?.base_params?.arrival_time_distribution ?? {}
    const frequency = distribution.frequency
    if (frequency?.events) {
      beginParameterEdit('arrival', 'arrival', 'arrival rate', {
        events: Number(frequency.events),
        per_count: Number(frequency.per_count ?? 1),
        per_unit: frequency.per_unit ?? 'week',
      })
      return
    }
    const seconds = Number(distribution.distribution_params?.[1]?.value ?? 604800)
    beginParameterEdit('arrival', 'arrival', 'arrival rate', {
      events: 1,
      per_count: seconds,
      per_unit: 'second',
    })
  }

  function openResourceEdit(resource: any) {
    const first = resource.resource_list?.[0] ?? {}
    beginParameterEdit('resource', resource.id, resource.name || resource.id, {
      headcount: resource.resource_list?.reduce((sum: number, item: any) => sum + Number(item.amount ?? 1), 0) ?? 1,
      cost_per_hour: Number(first.cost_per_hour ?? 0),
      calendar: first.calendar ?? calendarOptions.value[0]?.value,
    })
  }

  function openTaskDurationEdit(task: any) {
    const params = task.resources?.[0]?.distribution_params ?? []
    beginParameterEdit('task_duration', task.task_id, `${humanize(task.task_id)} duration`, {
      mean_minutes: Number(params[0]?.value ?? 0) / 60,
      stddev_minutes: Number(params[1]?.value ?? 0) / 60,
    })
  }

  function openGatewayEdit(gateway: any) {
    beginParameterEdit('gateway', gateway.gateway_id, humanizeGateway(gateway.gateway_id), {
      paths: gateway.probabilities.map((item: any) => ({
        path_id: item.path_id,
        percent: Number(item.value) * 100,
      })),
    })
  }

  async function saveBaselineParameter() {
    parameterEditError.value = ''
    if (parameterJustification.value.trim().length < 3) {
      parameterEditError.value = 'Provide a short reason for the change.'
      return
    }
    if (!parameterReviewerId.value.trim()) {
      parameterEditError.value = 'Provide a reviewer identifier.'
      return
    }
    parameterSaving.value = true
    try {
      let values = { ...parameterEditValues.value }
      if (parameterEditKind.value === 'gateway') {
        values = {
          probabilities: Object.fromEntries(
            parameterEditValues.value.paths.map((item: any) => [item.path_id, Number(item.percent) / 100]),
          ),
        }
      }
      const response = await fetch(`/api/projects/${encodeURIComponent(props.name)}/baseline-parameters`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          parameter_type: parameterEditKind.value,
          entity_id: parameterEditEntityId.value,
          values,
          justification: parameterJustification.value.trim(),
          reviewer_id: parameterReviewerId.value.trim(),
          evidence_type: parameterEvidenceType.value,
        }),
      })
      const payload = await response.json()
      if (!response.ok) {
        throw new Error(typeof payload.detail === 'string' ? payload.detail : `Save failed (HTTP ${response.status})`)
      }
      if (project.value) {
        project.value.base_params = payload.base_params
        project.value.results_stale = payload.results_stale
      }
      parameterEditDialog.value = false
    } catch (error: any) {
      parameterEditError.value = error?.message || 'Could not save the baseline parameter.'
    } finally {
      parameterSaving.value = false
    }
  }

  async function confirmDelete() {
    deleting.value = true
    try {
      const res = await fetch(`/api/projects/${encodeURIComponent(props.name)}`, {
        method: 'DELETE'
      })
      if (res.ok) {
        deleteDialog.value = false
        router.push('/')
      } else {
        console.error('Failed to delete project')
      }
    } catch (e) {
      console.error('Error deleting project:', e)
    } finally {
      deleting.value = false
    }
  }

  // ── BPMN diagram ────────────────────────────────────────────────────────────
  const bpmnXml        = ref('')
  const bpmnXmlLoading = ref(false)
  const bpmnXmlError   = ref('')

  async function fetchBpmnXml() {
    bpmnXmlLoading.value = true
    bpmnXmlError.value   = ''
    try {
      const res = await fetch(`/api/projects/${encodeURIComponent(props.name)}/bpmn`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      bpmnXml.value = await res.text()
    } catch {
      bpmnXmlError.value = 'Could not load BPMN diagram.'
    } finally {
      bpmnXmlLoading.value = false
    }
  }

  // ── Analytics for ANALYZE mode ───────────────────────────────────────────────
  const analyticsScenarios = ref<any[]>([])
  const analyticsLoading   = ref(false)
  const diagramScenario    = ref('')

  async function fetchAnalyticsForDiagram() {
    analyticsLoading.value = true
    try {
      const res = await fetch(`/api/projects/${encodeURIComponent(props.name)}/analytics`)
      if (!res.ok) return
      const data = await res.json()
      analyticsScenarios.value = data.scenarios ?? []
      if (analyticsScenarios.value.length) {
        diagramScenario.value = ''  // start with no scenario selected → VIEW mode
      }
    } catch { /* silent — diagram still shows in VIEW mode */ }
    finally { analyticsLoading.value = false }
  }

  /** Parse BPMN XML and return a Map<activityName, elementId> */
  function buildBpmnNameMap(xml: string): Map<string, string> {
    const map = new Map<string, string>()
    try {
      const doc = new DOMParser().parseFromString(xml, 'text/xml')
      const TASK_TYPES = ['task','userTask','serviceTask','manualTask',
                          'businessRuleTask','scriptTask','sendTask',
                          'receiveTask','subProcess','callActivity']
      for (const tag of TASK_TYPES) {
        const els = doc.getElementsByTagNameNS('*', tag)
        for (const el of Array.from(els)) {
          const id   = el.getAttribute('id')
          const name = el.getAttribute('name')
          if (id && name) map.set(name.trim(), id)
        }
      }
    } catch { /* ignore parse errors */ }
    return map
  }

  /** Values object for AureaEden ANALYZE mode: elementId → avg wait seconds */
  const diagramValues = computed<Record<string, number>>(() => {
    if (!bpmnXml.value || !analyticsScenarios.value.length) return {}
    const nameToId = buildBpmnNameMap(bpmnXml.value)
    const scenario = analyticsScenarios.value.find(s => s.scenario === diagramScenario.value)
                  ?? analyticsScenarios.value[0]
    if (!scenario) return {}

    const result: Record<string, number> = {}

    // Apply the actual scenario values (only positive wait times)
    for (const act of scenario.activities as any[]) {
      let id = nameToId.get(act.activity)
      if (!id) {
        const stripped = act.activity.replace(/\s*\([^)]+\)$/, '').trim()
        id = nameToId.get(stripped)
      }
      if (id && act.avg_wait_s > 0) {
        result[id] = act.avg_wait_s
      }
    }
    return result
  })

  const showPreview = ref(false)
  const currentPreviewFile = ref('')
  const previewContent = ref('')
  const reportContent = ref('')
  const reportLoading = ref(false)

  const isPreviewPdf = computed(() => currentPreviewFile.value.toLowerCase().endsWith('.pdf'))
  const isPreviewText = computed(() => {
    const ext = currentPreviewFile.value.toLowerCase().split('.').pop()
    return ['tex', 'md', 'txt', 'json'].includes(ext || '')
  })

  const renderedReport = computed(() => {
    if (!reportContent.value) return ''
    return marked.parse(reportContent.value) as string
  })

  function reportFileByExt(ext: string): string | undefined {
    return project.value?.reports?.find(r => r.toLowerCase().endsWith(`.${ext}`))
  }

  const hasReportFiles = computed(() =>
    ['docx', 'pdf', 'tex'].some(ext => !!reportFileByExt(ext))
  )

  async function fetchReport() {
    if (!props.name) return
    reportLoading.value = true
    try {
      const res = await fetch(`/api/projects/${props.name}/report`)
      if (res.ok) {
        reportContent.value = await res.text()
      } else {
        reportContent.value = ''
      }
    } catch {
      reportContent.value = ''
    } finally {
      reportLoading.value = false
    }
  }

  watch(activeTab, (tab) => {
    if (tab === 'reports' && !reportContent.value) {
      fetchReport()
    }
  })

  function resourceDiffs(scenario: any, idx: number) {
    if (idx === 0) return []
    // scenarios[0].resource_allocations is typically absent (baseline = base_params as-is).
    // Build a true baseline headcount map from base_params.resource_profiles.
    const baselineOverrides = project.value?.exp_params?.scenarios[0]?.resource_allocations || {}
    const baseProfiles: Record<string, number> = {}
    for (const res of project.value?.base_params?.resource_profiles ?? []) {
      baseProfiles[res.name] = res.resource_list.reduce((s: number, r: any) => s + (r.amount ?? 1), 0)
    }
    const current = scenario.resource_allocations || {}
    return Object.entries(current)
      .map(([role, count]) => {
        const baseline = role in baselineOverrides ? baselineOverrides[role] : (baseProfiles[role] ?? 0)
        return { role, baseline, new: count }
      })
      .filter(d => d.new !== d.baseline)
  }

  function costDiffs(scenario: any, idx: number) {
    if (idx === 0) return []
    const baseline = project.value?.exp_params?.scenarios[0]?.cost_overrides || {}
    const current = scenario.cost_overrides || {}
    return Object.entries(current)
      .filter(([role, cost]) => cost !== baseline[role])
      .map(([role, cost]) => ({ role, new: cost }))
  }

  function staffingChipLabel(scenario: any, idx: number): string | null {
    const diffs = resourceDiffs(scenario, idx)
    if (!diffs.length) return null
    const allUp = diffs.every((d: any) => d.new > d.baseline)
    const allDown = diffs.every((d: any) => d.new < d.baseline)
    // Check if all diffs share the same integer multiplier (e.g. all 1→2)
    if (allUp) {
      const ratios = diffs.map((d: any) => (d.baseline > 0 ? Number(d.new) / Number(d.baseline) : null)).filter(Boolean) as number[]
      const first = ratios[0]
      if (first !== undefined && ratios.every(r => Math.abs(r - first) < 0.01)) {
        return `↑ ${Number.isInteger(first) ? first : first.toFixed(1)}× headcount`
      }
      return '↑ Staffing increased'
    }
    if (allDown) return '↓ Staffing reduced'
    return '↕ Staffing revised'
  }

  function scenarioFallbackDescription(scenario: any, idx: number): string {
    if (idx === 0) return 'The reference configuration using standard staffing and normal operational demand.'
    const baseRate = project.value?.exp_params?.scenarios[0]?.arrival_rate ?? 144000
    const rateDiff = scenario.arrival_rate < baseRate
      ? `${Math.round(baseRate / scenario.arrival_rate)}× higher demand`
      : 'standard demand'
    const diffs = resourceDiffs(scenario, idx)
    const staffNote = diffs.length > 0
      ? `with ${diffs.filter((d: any) => d.new > d.baseline).length > 0 ? 'increased' : 'reduced'} staffing`
      : 'with unchanged staffing'
    return `Tests the process under ${rateDiff} ${staffNote}.`
  }

  function getFileIcon(filename: string): string {
    const ext = filename.toLowerCase().split('.').pop()
    if (ext === 'pdf') return 'mdi-file-pdf-box'
    if (ext === 'docx') return 'mdi-file-word'
    if (ext === 'tex') return 'mdi-code-braces'
    return 'mdi-file-document'
  }

  async function previewReport(filename: string) {
    currentPreviewFile.value = filename
    previewContent.value = ''
    
    const ext = filename.toLowerCase().split('.').pop()
    if (isPreviewText.value) {
      try {
        const res = await fetch(`/api/projects/${props.name}/download/${filename}`)
        previewContent.value = await res.text()
      } catch (e) {
        previewContent.value = 'Failed to load preview.'
      }
    }
    
    showPreview.value = true
  }

  const coreKpiKeys = computed(() => {
    if (!project.value?.kpis?.length) return []
    return Object.keys(project.value.kpis[0]).filter(k => !k.startsWith('Wait_Time_Hrs_'))
  })

  const kpiHeaders = computed(() =>
    coreKpiKeys.value.map(key => ({ title: humanize(key), key, sortable: true }))
  )

  const humanizedKpis = computed(() => {
    if (!project.value?.kpis?.length) return []
    return project.value.kpis.map(row => {
      const out: Record<string, string | number> = {}
      coreKpiKeys.value.forEach(k => { out[k] = (row as any)[k] })
      if (typeof out['Scenario'] === 'string') out['Scenario'] = humanize(out['Scenario'])
      return out
    })
  })

  const waitTimeKeys = computed(() => {
    if (!project.value?.kpis?.length) return []
    return Object.keys(project.value.kpis[0]).filter(k => k.startsWith('Wait_Time_Hrs_'))
  })

  const waitTimeHeaders = computed(() => {
    const headers: any[] = [{ title: 'Scenario', key: 'Scenario', sortable: true }]
    waitTimeKeys.value.forEach(k => {
      headers.push({ title: humanize(k.replace('Wait_Time_Hrs_', '')), key: k, sortable: true })
    })
    return headers
  })

  const waitTimeRows = computed(() => {
    if (!project.value?.kpis?.length) return []
    return project.value.kpis.map(row => {
      const out: Record<string, any> = {
        Scenario: typeof (row as any)['Scenario'] === 'string' ? humanize((row as any)['Scenario']) : (row as any)['Scenario']
      }
      waitTimeKeys.value.forEach(k => { out[k] = (row as any)[k] })
      return out
    })
  })

  const arrivalRateMean = computed(() => {
    const dist = project.value?.base_params?.arrival_time_distribution
    if (!dist) return '—'
    const secs = dist.distribution_params?.[1]?.value ?? 0
    return formatInterval(secs)
  })

  const arrivalRateEffective = computed(() => {
    const dist = project.value?.base_params?.arrival_time_distribution
    const cal = project.value?.base_params?.arrival_time_calendar
    if (!dist || !cal?.length) return null
    const meanSecs = dist.distribution_params?.[1]?.value ?? 0
    if (!meanSecs) return null
    const dayOrder = ['MONDAY','TUESDAY','WEDNESDAY','THURSDAY','FRIDAY','SATURDAY','SUNDAY']
    let workingSecsPerWeek = 0
    for (const period of cal) {
      const [bh, bm] = (period.beginTime ?? '08:00:00').split(':').map(Number)
      const [eh, em] = (period.endTime ?? '16:00:00').split(':').map(Number)
      const hoursPerDay = (eh + em / 60) - (bh + bm / 60)
      const fromIdx = dayOrder.indexOf(period.from ?? 'MONDAY')
      const toIdx = dayOrder.indexOf(period.to ?? 'FRIDAY')
      const days = toIdx >= fromIdx ? toIdx - fromIdx + 1 : 0
      workingSecsPerWeek += days * hoursPerDay * 3600
    }
    if (!workingSecsPerWeek) return null
    const perWeek = workingSecsPerWeek / meanSecs
    if (perWeek >= 1) return `~${perWeek % 1 < 0.1 ? Math.round(perWeek) : perWeek.toFixed(1)} / week`
    const perMonth = perWeek * 4.33
    if (perMonth >= 1) return `~${perMonth.toFixed(1)} / month`
    return `~${(perWeek * 52).toFixed(0)} / year`
  })

  const DISTRIBUTION_NAMES: Record<string, string> = {
    norm:    'Normal',
    expon:   'Exponential',
    lognorm: 'Log-Normal',
    gamma:   'Gamma',
    uniform: 'Uniform',
    fix:     'Fixed',
    fixed:   'Fixed',
    erlang:  'Erlang',
    triang:  'Triangular',
  }
  function formatDistribution(code: string | undefined): string {
    if (!code) return '—'
    return DISTRIBUTION_NAMES[code.toLowerCase()] ?? code
  }

  function sourceLabel(title: string | undefined, url: string): string {
    const BAD = 'vertexaisearch.cloud.google.com'
    if (title && !title.includes(BAD)) return title
    // Fall back to URL path without protocol (always readable)
    return url.replace(/^https?:\/\//, '')
  }

  function formatInterval (seconds: number): string {
    if (!seconds) return '—'
    const d = Math.floor(seconds / 86400)
    const h = Math.floor((seconds % 86400) / 3600)
    const m = Math.floor((seconds % 3600) / 60)
    const parts: string[] = []
    if (d > 0) parts.push(`${d} day${d > 1 ? 's' : ''}`)
    if (h > 0) parts.push(`${h} hr${h > 1 ? 's' : ''}`)
    if (m > 0 && d === 0) parts.push(`${m} min`)
    return parts.join(' ') || `${seconds}s`
  }

  function formatDate (timestamp?: number): string {
    if (!timestamp) return 'Loading...'
    return new Date(timestamp * 1000).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  function humanize (name: string): string {
    return name
      .replace(/[-_]/g, ' ')
      .replace(/([a-z])([A-Z])/g, '$1 $2')
      .replace(/\b\w/g, c => c.toUpperCase())
  }

  function runNumber (folderName: string): string | null {
    const match = folderName.match(/-(\d+)$/)
    return match ? match[1] : null
  }

  function humanizeGateway (id: string): string {
    return id.replace(/^Gateway_/i, '').replace(/[-_]/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
  }

  function formatTimePeriod (period: any): string {
    const d: Record<string, string> = {
      MONDAY: 'Mon', TUESDAY: 'Tue', WEDNESDAY: 'Wed', THURSDAY: 'Thu',
      FRIDAY: 'Fri', SATURDAY: 'Sat', SUNDAY: 'Sun'
    }
    const from = d[period.from] ?? period.from
    const to = d[period.to] ?? period.to
    const begin = (period.beginTime ?? '').substring(0, 5)
    const end = (period.endTime ?? '').substring(0, 5)
    return `${from}\u2013${to}  ${begin}\u2013${end}`
  }

  onMounted(async () => {
    fetchBpmnXml()
    fetchAnalyticsForDiagram()
    try {
      const res = await fetch(`/api/projects/${props.name}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      project.value = await res.json()
    } catch (e) {
      console.error('Failed to load project:', e)
    } finally {
      loading.value = false
    }
  })
</script>

<style scoped>
/* ── Transitions ─────────────────────────────────────────────── */
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from, .fade-leave-to       { opacity: 0; }

/* ── Report Markdown Renderer ─────────────────────────────────── */
.report-markdown {
  font-size: 0.9375rem;
  line-height: 1.75;
  color: inherit;
}

.report-markdown :deep(h1),
.report-markdown :deep(h2),
.report-markdown :deep(h3),
.report-markdown :deep(h4) {
  font-weight: 700;
  margin-top: 1.75em;
  margin-bottom: 0.5em;
  line-height: 1.3;
}

.report-markdown :deep(h1) { font-size: 1.75rem; }
.report-markdown :deep(h2) {
  font-size: 1.25rem;
  padding-bottom: 0.4em;
  border-bottom: 1px solid rgba(128,128,128,0.2);
}
.report-markdown :deep(h3) { font-size: 1.05rem; }
.report-markdown :deep(h4) { font-size: 0.95rem; text-transform: uppercase; letter-spacing: 0.05em; opacity: 0.75; }

.report-markdown :deep(p) {
  margin-top: 0;
  margin-bottom: 1em;
}

.report-markdown :deep(ul),
.report-markdown :deep(ol) {
  padding-left: 1.5em;
  margin-bottom: 1em;
}

.report-markdown :deep(li) {
  margin-bottom: 0.3em;
}

.report-markdown :deep(strong) {
  font-weight: 700;
}

.report-markdown :deep(em) {
  font-style: italic;
}

.report-markdown :deep(blockquote) {
  margin: 1em 0;
  padding: 0.75em 1.25em;
  border-left: 4px solid rgb(var(--v-theme-primary));
  background: rgba(var(--v-theme-primary), 0.06);
  border-radius: 0 6px 6px 0;
  font-style: italic;
  opacity: 0.9;
}

.report-markdown :deep(code) {
  font-family: 'Roboto Mono', 'Fira Code', monospace;
  font-size: 0.85em;
  padding: 0.15em 0.4em;
  border-radius: 4px;
  background: rgba(128,128,128,0.15);
}

.report-markdown :deep(pre) {
  margin: 1em 0;
  padding: 1em 1.25em;
  border-radius: 8px;
  background: rgba(128,128,128,0.1);
  overflow-x: auto;
}

.report-markdown :deep(pre code) {
  background: none;
  padding: 0;
}

.report-markdown :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 1em 0;
  font-size: 0.875rem;
}

.report-markdown :deep(th),
.report-markdown :deep(td) {
  padding: 0.6em 1em;
  border: 1px solid rgba(128,128,128,0.2);
  text-align: left;
}

.report-markdown :deep(th) {
  font-weight: 700;
  background: rgba(var(--v-theme-primary), 0.08);
}

.report-markdown :deep(tr:nth-child(even) td) {
  background: rgba(128,128,128,0.04);
}

.report-markdown :deep(a) {
  color: rgb(var(--v-theme-primary));
  text-decoration: none;
}

.report-markdown :deep(a:hover) {
  text-decoration: underline;
}

.report-markdown :deep(hr) {
  border: none;
  border-top: 1px solid rgba(128,128,128,0.2);
  margin: 2em 0;
}
</style>

