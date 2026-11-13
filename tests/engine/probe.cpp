#include "test/test.h"
#include <fstream>
#include <cstdlib>

std::string input(Stage& stage, const std::string& events) {
  KeySequence output;
  for (const auto& event : parse_sequence(events.data(), events.data() + events.size()))
    for (const auto& key : stage.update(event, 0))
      output.push_back(key);
  return format_sequence(output);
}

TEST_CASE("direction mapping semantics") {
  std::ifstream file(std::getenv("KM_PROBE_CONFIG"));
  REQUIRE(file.good());
  std::ostringstream config;
  config << file.rdbuf();

  SECTION("left shift can be released first") {
    auto stage = create_stage(config.str().c_str());
    CHECK(input(stage, "+ShiftLeft +D").find("+ArrowLeft") != std::string::npos);
    CHECK(input(stage, "-ShiftLeft").find("-ArrowLeft") != std::string::npos);
    CHECK(input(stage, "+D -D").find("+ArrowLeft") == std::string::npos);
  }

  SECTION("letter without the modifier is delivered immediately") {
    auto stage = create_stage(config.str().c_str());
    CHECK(input(stage, "+D") == "+D");
    CHECK(input(stage, "-D") == "-D");
  }

  SECTION("all remaining default directions") {
    auto stage = create_stage(config.str().c_str());
    CHECK(input(stage, "+ShiftLeft +F -F -ShiftLeft").find("+ArrowUp") != std::string::npos);
    CHECK(input(stage, "+ShiftLeft +J -J -ShiftLeft").find("+ArrowDown") != std::string::npos);
    CHECK(input(stage, "+ShiftLeft +K -K -ShiftLeft").find("+ArrowRight") != std::string::npos);
  }
  SECTION("extra modifier blocks mapping") {
    auto stage = create_stage(config.str().c_str());
    CHECK(input(stage, "+ControlLeft +ShiftLeft +D -D -ShiftLeft -ControlLeft")
      .find("ArrowLeft") == std::string::npos);
  }

  SECTION("right shift remains ordinary") {
    auto stage = create_stage(config.str().c_str());
    CHECK(input(stage, "+ShiftRight +D -D -ShiftRight") == "+ShiftRight +D -D -ShiftRight");
  }

  SECTION("repeat while held") {
    auto stage = create_stage(config.str().c_str());
    CHECK(input(stage, "+ShiftLeft +D").find("+ArrowLeft") != std::string::npos);
    CHECK(input(stage, "+D").find("+ArrowLeft") != std::string::npos);
    CHECK(input(stage, "-D -ShiftLeft").find("-ArrowLeft") != std::string::npos);
  }
}


