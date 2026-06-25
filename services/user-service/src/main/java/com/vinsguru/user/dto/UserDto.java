package com.vinsguru.user.dto;

import java.util.List;

public record UserDto(Integer id,
                      String name,
                      String email,
                      String tier,
                      String role,
                      List<TitleDto> recommendations) {
}
