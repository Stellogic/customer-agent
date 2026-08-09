FROM gradle:9.3.1-jdk25 AS build
ARG GRADLE_OPTS
WORKDIR /workspace
COPY settings.gradle.kts build.gradle.kts gradle.lockfile ./
COPY src ./src
RUN gradle bootJar --no-daemon

FROM build AS test
RUN gradle test --no-daemon

FROM eclipse-temurin:25.0.3_9-jre-noble AS runtime
RUN apt-get update \
    && apt-get install --yes --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --system --uid 10001 --create-home app
USER app
WORKDIR /app
COPY --from=build /workspace/build/libs/customer-agent-backend-0.1.0-SNAPSHOT.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
