/*
 * SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package controllers

import (
	"github.com/ai-dynamo/dynamo/deploy/dynamo/api-server/api/mocks"
	"github.com/ai-dynamo/dynamo/deploy/dynamo/api-server/api/schemas"
	"github.com/gin-gonic/gin"
)

type organizationMemberController struct {
	organizationController
}

var OrganizationMemberController = organizationMemberController{}

func (c *organizationMemberController) Create(ctx *gin.Context) {
	ctx.JSON(501, gin.H{"error": "not supported."})
}

func (c *organizationMemberController) List(ctx *gin.Context) {
	organizationMemberSchemaList := []*schemas.OrganizationMemberSchema{mocks.DefaultOrgMember()}
	ctx.JSON(200, organizationMemberSchemaList)
}

func (c *organizationMemberController) Delete(ctx *gin.Context) {
	ctx.JSON(501, gin.H{"error": "not supported."})
}
